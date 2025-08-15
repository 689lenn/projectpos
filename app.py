from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename
from sqlalchemy.sql import func
from datetime import datetime
from flask import jsonify
from sqlalchemy.orm import joinedload
import os, secrets, string

app = Flask(__name__)
app.secret_key = 'pos_secret_key'

# ==================== CONFIG ====================
basedir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'database.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = os.path.join(basedir, 'static', 'uploads')
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

db = SQLAlchemy(app)

# ==================== MODELS ====================
class Kategori(db.Model):
    __tablename__ = 'kategori'
    id   = db.Column(db.Integer, primary_key=True)
    nama = db.Column(db.String(100), nullable=False, unique=True)
    produk = db.relationship('Produk', back_populates='kategori', lazy='select')

class Produk(db.Model):
    __tablename__ = 'produk'
    id    = db.Column(db.Integer, primary_key=True)
    nama  = db.Column(db.String(100), nullable=False)
    harga = db.Column(db.Integer, nullable=False)  # harga utama
    hpp   = db.Column(db.Integer, nullable=False, default=0)  # <-- TAMBAH INI
    stok  = db.Column(db.Integer, nullable=False)
    foto  = db.Column(db.String(200), nullable=True)

    kategori_id = db.Column(db.Integer, db.ForeignKey('kategori.id'), nullable=True)
    kategori = db.relationship('Kategori', back_populates='produk')

    harga_list = db.relationship('ProdukHarga', backref='produk', cascade='all, delete-orphan', lazy='select')

class Customer(db.Model):
    __tablename__ = 'customer'
    id         = db.Column(db.Integer, primary_key=True)
    nama       = db.Column(db.String(100), nullable=False)
    email      = db.Column(db.String(100), nullable=False)
    no_telepon = db.Column(db.String(20), nullable=True)
    alamat     = db.Column(db.String(200), nullable=True)

class Room(db.Model):
    __tablename__ = 'room'
    id         = db.Column(db.Integer, primary_key=True)
    kode       = db.Column(db.String(12), unique=True, nullable=False)
    status     = db.Column(db.String(20), nullable=False, default='open')  # open/closed
    created_at = db.Column(db.DateTime, server_default=func.now())
    items      = db.relationship('RoomItem', backref='room', cascade='all, delete')

class RoomItem(db.Model):
    __tablename__ = 'room_item'
    id        = db.Column(db.Integer, primary_key=True)
    room_id   = db.Column(db.Integer, db.ForeignKey('room.id'), nullable=False)
    produk_id = db.Column(db.Integer, db.ForeignKey('produk.id'), nullable=False)
    jumlah    = db.Column(db.Integer, nullable=False, default=0)
    harga     = db.Column(db.Integer, nullable=False, default=0)  # snapshot harga saat masuk

class Transaksi(db.Model):
    __tablename__ = 'transaksi'
    id         = db.Column(db.Integer, primary_key=True)
    tanggal    = db.Column(db.String(20), nullable=False)
    total      = db.Column(db.Integer, nullable=False, default=0)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=True)
    bayar       = db.Column(db.Integer, nullable=True, default=0)
    kembalian   = db.Column(db.Integer, nullable=True, default=0)

    customer = db.relationship('Customer')
    item_transaksi = db.relationship("ItemTransaksi", backref="transaksi", cascade="all, delete")

class ItemTransaksi(db.Model):
    __tablename__ = 'item_transaksi'
    id            = db.Column(db.Integer, primary_key=True)
    transaksi_id  = db.Column(db.Integer, db.ForeignKey('transaksi.id'), nullable=False)
    produk_id     = db.Column(db.Integer, db.ForeignKey('produk.id'), nullable=False)
    jumlah        = db.Column(db.Integer, nullable=False)
    produk = db.relationship("Produk")

class ProdukHarga(db.Model):
    __tablename__ = 'produk_harga'
    id        = db.Column(db.Integer, primary_key=True)
    produk_id = db.Column(db.Integer, db.ForeignKey('produk.id'), nullable=False)
    label     = db.Column(db.String(100), nullable=False)     # contoh: "Retail", "Grosir", "Promo"
    harga     = db.Column(db.Integer, nullable=False, default=0)
    is_default = db.Column(db.Boolean, nullable=False, default=False)

with app.app_context():
    db.create_all()

@app.route('/cart/count')
def cart_count_api():
    cart = get_cart_dict_for_template()
    count = sum(item.get("jumlah", 0) for item in cart.values())
    return jsonify({"count": count})

# ==================== UTIL & FILTER ====================
def get_default_price(produk: 'Produk'):
    """Kembalikan harga default dari ProdukHarga jika ada, kalau tidak pakai produk.harga."""
    if not produk:
        return 0
    for ph in produk.harga_list:
        if ph.is_default:
            return ph.harga
    return produk.harga

@app.template_filter("format_tanggal")
def format_tanggal_filter(value):
    try:
        return datetime.strptime(value, "%Y-%m-%d").strftime("%d/%m/%Y")
    except Exception:
        return value

def gen_room_code(n=6):
    alphabet = string.ascii_uppercase + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(n))

def ensure_room():
    """Shim: room bersifat opsional. Fungsi ini hanya menjaga kompatibilitas (tidak membuat room baru)."""
    return session.get('room_code')

def get_current_room():
    """Kembalikan object Room aktif berdasarkan session['room_code'], atau None."""
    code = session.get('room_code')
    if not code:
        return None
    return Room.query.filter_by(kode=code, status='open').first()

def get_cart_dict_for_template():
    """
    Keranjang untuk template:
    - Jika ada Room aktif → ambil dari RoomItem (DB).
    - Jika tidak ada Room aktif → ambil dari session['cart'] (dict).
    Format dict:
      { "pid": {"nama":..., "harga":..., "jumlah":..., "foto":..., "stok":...} }
    """
    room = get_current_room()
    result = {}
    if room:
        items = RoomItem.query.filter_by(room_id=room.id).all()
        for it in items:
            p = Produk.query.get(it.produk_id)
            if p:
                result[str(p.id)] = {
                    "nama": p.nama,
                    "harga": it.harga if it.harga else p.harga,
                    "jumlah": it.jumlah,
                    "foto": p.foto,
                    "stok": p.stok
                }
        return result
    else:
        return session.get('cart', {})

@app.template_filter("rupiah")
def rupiah_filter(n):
    try:
        return "Rp " + f"{int(n):,}".replace(",", ".")
    except Exception:
        try:
            return "Rp " + f"{float(n):,.0f}".replace(",", ".")
        except Exception:
            return f"Rp {n}"
            
@app.context_processor
def inject_globals():
    """
    Inject ke template:
      - current_room → Room aktif (atau None)
      - cart_count   → jumlah item di keranjang (RoomItem atau session), konsisten
    """
    room = get_current_room()
    # gunakan keranjang gabungan yang sama dengan keranjang.html
    cart = get_cart_dict_for_template()
    count = sum(item.get("jumlah", 0) for item in cart.values())
    return {"current_room": room, "cart_count": count}

# ==================== HALAMAN UTAMA ====================
@app.route("/")
def index():
    ensure_room()
    daftar_produk   = Produk.query.all()
    daftar_kategori = Kategori.query.order_by(Kategori.nama.asc()).all()
    # tampilkan hanya room yang masih open
    daftar_rooms    = Room.query.filter_by(status='open').order_by(Room.created_at.desc()).all()

    # susun harga per produk (untuk modal)
    harga_map = {}
    for p in daftar_produk:
        options = []
        for ph in p.harga_list:
            options.append({"id": ph.id, "label": ph.label, "harga": ph.harga, "default": ph.is_default})
        harga_map[p.id] = {"utama": p.harga, "opsi": options}

    return render_template(
        "index.html",
        daftar_produk=daftar_produk,
        daftar_kategori=daftar_kategori,
        daftar_rooms=daftar_rooms,
        harga_map=harga_map
    )

# ==================== KERANJANG (ROOM / SESSION) ====================
@app.route("/tambah_keranjang", methods=["POST"])
def tambah_keranjang():
    produk_id   = request.form.get("produk_id")
    harga_id    = request.form.get("harga_id")      # opsional: id ProdukHarga
    harga_manual = request.form.get("harga_manual") # opsional: override manual
    qty = int(request.form.get("jumlah") or request.form.get("qty") or 0)

    if not produk_id or qty <= 0:
        flash("Jumlah tidak valid.", "error")
        return redirect(url_for("index"))

    p = Produk.query.get_or_404(int(produk_id))

    # ==== Tentukan harga snapshot ====
    snap_price = None

    # 1) Prioritas tertinggi: harga manual
    if harga_manual:
        try:
            hm = int(harga_manual)
            if hm > 0:
                snap_price = hm
        except:
            pass

    # 2) Jika tidak ada manual: coba harga_id
    if snap_price is None and harga_id and harga_id.isdigit():
        ph = ProdukHarga.query.get(int(harga_id))
        if ph and ph.produk_id == p.id:
            snap_price = ph.harga

    # 3) Fallback: default ProdukHarga (jika ada) → harga utama
    if snap_price is None:
        snap_price = get_default_price(p)

    room = get_current_room()
    if room:
        it = RoomItem.query.filter_by(room_id=room.id, produk_id=p.id).first()
        if it:
            it.jumlah += qty
            it.harga = snap_price
        else:
            db.session.add(RoomItem(room_id=room.id, produk_id=p.id, jumlah=qty, harga=snap_price))
        db.session.commit()
    else:
        cart = session.get('cart', {})
        key = str(p.id)
        if key in cart:
            cart[key]["jumlah"] += qty
            cart[key]["harga"] = snap_price
        else:
            cart[key] = {"nama": p.nama, "harga": snap_price, "jumlah": qty, "foto": p.foto}
        session['cart'] = cart
        session.modified = True

    flash(f"{p.nama} x{qty} ditambahkan ke keranjang.", "success")
    return redirect(url_for("index"))

@app.route("/keranjang", endpoint="keranjang_view")
def keranjang_view():
    cart = get_cart_dict_for_template()
    room = get_current_room()

    if not room:
        for pid, item in cart.items():
            p = Produk.query.get(int(pid))
            item["stok"] = p.stok if p else 0

    # Modal = HPP produk
    produk_hpp = {}
    for pid, item in cart.items():
        p = Produk.query.get(int(pid))
        produk_hpp[pid] = (p.hpp if p and p.hpp is not None else 0)

    total = sum(item["harga"] * item["jumlah"] for item in cart.values())
    pot_profit = sum((item["harga"] - produk_hpp.get(pid, 0)) * item["jumlah"] for pid, item in cart.items())

    return render_template(
        "keranjang.html",
        keranjang=cart,
        total=total,
        produk_hpp=produk_hpp,
        pot_profit=pot_profit
    )

@app.route("/keranjang/update", methods=["POST"])
def keranjang_update():
    """Update jumlah item (0 = hapus)."""
    room = get_current_room()
    keys = request.form.getlist("key[]")
    qtys = request.form.getlist("qty[]") or request.form.getlist("jumlah[]")

    if room:
        for key, q in zip(keys, qtys):
            pid = int(key)
            q_int = max(0, int(q or 0))
            it = RoomItem.query.filter_by(room_id=room.id, produk_id=pid).first()
            if it:
                if q_int == 0:
                    db.session.delete(it)
                else:
                    it.jumlah = q_int
        db.session.commit()
    else:
        cart = session.get('cart', {})
        for key, q in zip(keys, qtys):
            q_int = max(0, int(q or 0))
            if key in cart:
                if q_int == 0:
                    cart.pop(key, None)
                else:
                    cart[key]["jumlah"] = q_int
        session['cart'] = cart
        session.modified = True

    return redirect(url_for("keranjang_view"))

@app.route("/keranjang/hapus/<pid>", methods=["POST"], endpoint="hapus_item_keranjang")
def keranjang_hapus(pid):
    room = get_current_room()
    if room:
        it = RoomItem.query.filter_by(room_id=room.id, produk_id=int(pid)).first()
        if it:
            db.session.delete(it)
            db.session.commit()
    else:
        cart = session.get('cart', {})
        cart.pop(pid, None)
        session['cart'] = cart
        session.modified = True
    return redirect(url_for("keranjang_view"))

# ==================== PEMBAYARAN & CHECKOUT ====================
@app.route("/pembayaran", methods=["GET", "POST"])
def pembayaran():
    cart = get_cart_dict_for_template()
    if not cart:
        flash("Keranjang kosong.", "error")
        return redirect(url_for("keranjang_view"))

    total = sum(item["harga"] * item["jumlah"] for item in cart.values())

    if request.method == "POST":
        # izinkan stok minus → tidak validasi stok di sini
        customer_id = request.form.get("customer_id")
        bayar = int(request.form.get("bayar") or 0)
        if bayar < total:
            flash("Nominal bayar kurang dari total.", "error")
            return redirect(url_for("pembayaran"))

        # Simpan transaksi
        tgl = datetime.now().strftime("%Y-%m-%d")
        trx = Transaksi(
            tanggal=tgl,
            total=total,
            customer_id=int(customer_id) if customer_id and customer_id.isdigit() else None,
            bayar=bayar,
            kembalian=bayar - total
        )
        db.session.add(trx)
        db.session.flush()

        # Simpan item & kurangi stok (bisa minus)
        for pid, item in cart.items():
            p = Produk.query.get(int(pid))
            if not p:
                continue
            p.stok -= item["jumlah"]
            db.session.add(ItemTransaksi(transaksi_id=trx.id, produk_id=p.id, jumlah=item["jumlah"]))

        # Jika checkout dari Room → close room & lepas dari session
        room = get_current_room()
        if room:
            room.status = 'closed'
            db.session.commit()
            session.pop('room_code', None)
        else:
            db.session.commit()

        # Bersihkan keranjang session (jika dipakai)
        session.pop("cart", None)

        flash("Transaksi berhasil disimpan.", "success")
        return redirect(url_for("transaksi_detail", id=trx.id))

    # GET → tampilkan form pembayaran
    customers = Customer.query.order_by(Customer.nama.asc()).all()
    return render_template("pembayaran.html", total=total, customers=customers)

# ==================== LAPORAN TRANSAKSI ====================
@app.route('/transaksi')
def transaksi_list():
    daftar_transaksi = Transaksi.query.order_by(Transaksi.id.desc()).all()
    return render_template('transaksi_list.html', daftar_transaksi=daftar_transaksi)

@app.route('/transaksi/<int:id>')
def transaksi_detail(id):
    transaksi = (
        Transaksi.query
        .options(
            joinedload(Transaksi.item_transaksi).joinedload(ItemTransaksi.produk),
            joinedload(Transaksi.customer)
        )
        .get_or_404(id)
    )
    return render_template('transaksi_detail.html', transaksi=transaksi)

# ==================== CRUD PRODUK ====================
@app.route('/produk')
def produk_list():
    daftar_produk = Produk.query.all()
    return render_template('produk_list.html', daftar_produk=daftar_produk)

@app.route('/produk/tambah', methods=['GET', 'POST'])
def produk_tambah():
    if request.method == 'POST':
        nama  = (request.form.get('nama') or '').strip()
        harga_utama = request.form.get('harga') or '0'
        hpp   = request.form.get('hpp') or '0'     # <-- TAMBAH INI
        stok  = request.form.get('stok') or '0'
        kategori_id = request.form.get('kategori_id')

        if not nama or not harga_utama.isdigit() or not stok.isdigit() or not hpp.isdigit():
            return "Input tidak valid", 400

        foto_file = request.files.get('foto')
        foto_filename = None
        if foto_file and foto_file.filename:
            foto_filename = secure_filename(foto_file.filename)
            foto_file.save(os.path.join(app.config['UPLOAD_FOLDER'], foto_filename))

        p = Produk(
            nama=nama,
            harga=int(harga_utama),
            hpp=int(hpp),                   # <-- SIMPAN HPP
            stok=int(stok),
            foto=foto_filename,
            kategori_id=int(kategori_id) if kategori_id and kategori_id.isdigit() else None
        )
        db.session.add(p)
        db.session.flush()  # dapat p.id

        # ==== tangkap multi harga (opsional) ====
        labels = request.form.getlist('harga_label[]')       # list label
        values = request.form.getlist('harga_value[]')       # list nilai
        default_key = request.form.get('harga_default')      # 'utama' atau 'row-<index>'

        for i, (lbl, val) in enumerate(zip(labels, values)):
            lbl = (lbl or '').strip()
            v = int(val or 0)
            if not lbl or v <= 0:
                continue
            is_def = (default_key == f'row-{i}')
            db.session.add(ProdukHarga(produk_id=p.id, label=lbl, harga=v, is_default=is_def))

        db.session.commit()
        return redirect(url_for('produk_list'))

    kategori = Kategori.query.order_by(Kategori.nama.asc()).all()
    return render_template('tambah_produk.html', kategori=kategori)

@app.route('/produk/edit/<int:id>', methods=['GET', 'POST'])
def produk_edit(id):
    produk = Produk.query.get_or_404(id)
    if request.method == 'POST':
        nama  = (request.form.get('nama') or '').strip()
        harga_utama = request.form.get('harga') or '0'
        hpp   = request.form.get('hpp') or '0'     # <-- TAMBAH INI
        stok  = request.form.get('stok') or '0'
        kategori_id = request.form.get('kategori_id')

        if not nama or not harga_utama.isdigit() or not stok.isdigit() or not hpp.isdigit():
            return "Input tidak valid", 400

        produk.nama  = nama
        produk.harga = int(harga_utama)
        produk.hpp   = int(hpp)                   # <-- SIMPAN HPP
        produk.stok  = int(stok)
        produk.kategori_id = int(kategori_id) if kategori_id and kategori_id.isdigit() else None

        foto_file = request.files.get('foto')
        if foto_file and foto_file.filename:
            foto_filename = secure_filename(foto_file.filename)
            foto_file.save(os.path.join(app.config['UPLOAD_FOLDER'], foto_filename))
            produk.foto = foto_filename

        # ====== proses harga tambahan ======
        existing_map = {str(ph.id): ph for ph in produk.harga_list}

        ids    = request.form.getlist('ph_id[]')          # bisa kosong (baris baru)
        labels = request.form.getlist('harga_label[]')
        values = request.form.getlist('harga_value[]')
        dels   = request.form.getlist('harga_hapus[]')    # id yang ditandai hapus
        default_key = request.form.get('harga_default')   # 'utama' atau 'row-<index>' atau 'id-<id>'

        # Set is_default False semua
        for ph in produk.harga_list:
            ph.is_default = False

        for i, (ph_id, lbl, val) in enumerate(zip(ids, labels, values)):
            lbl = (lbl or '').strip()
            v = int(val or 0)

            # baris dihapus?
            if ph_id and ph_id in dels:
                ph = existing_map.get(ph_id)
                if ph:
                    db.session.delete(ph)
                continue

            if not lbl or v <= 0:
                continue

            if ph_id:
                # update existing
                ph = existing_map.get(ph_id)
                if ph:
                    ph.label = lbl
                    ph.harga = v
                    ph.is_default = (default_key == f'id-{ph.id}')
            else:
                # baris baru
                is_def = (default_key == f'row-{i}')
                db.session.add(ProdukHarga(produk_id=produk.id, label=lbl, harga=v, is_default=is_def))

        db.session.commit()
        return redirect(url_for('produk_list'))

    kategori = Kategori.query.order_by(Kategori.nama.asc()).all()
    return render_template('produk_edit.html', produk=produk, kategori=kategori)

@app.route('/produk/hapus/<int:id>', methods=['POST'])
def produk_hapus(id):
    produk = Produk.query.get_or_404(id)
    db.session.delete(produk)
    db.session.commit()
    return redirect(url_for('produk_list'))

# ==================== CRUD CUSTOMER ====================
@app.route('/customer')
def customer_list():
    customers = Customer.query.all()
    return render_template('customer_list.html', customers=customers)

@app.route('/customer/tambah', methods=['GET', 'POST'])
def customer_tambah():
    if request.method == 'POST':
        nama = (request.form.get('nama') or '').strip()
        email = (request.form.get('email') or '').strip()
        no_telepon = request.form.get('no_telepon')
        alamat     = request.form.get('alamat')

        if not nama or not email:
            return "Input tidak valid", 400

        customer = Customer(nama=nama, email=email, no_telepon=no_telepon, alamat=alamat)
        db.session.add(customer)
        db.session.commit()
        return redirect(url_for('customer_list'))
    return render_template('customer_tambah.html')

@app.route('/customer/edit/<int:id>', methods=['GET', 'POST'])
def customer_edit(id):
    customer = Customer.query.get_or_404(id)
    if request.method == 'POST':
        nama = (request.form.get('nama') or '').strip()
        email = (request.form.get('email') or '').strip()
        no_telepon = request.form.get('no_telepon')
        alamat     = request.form.get('alamat')

        if not nama or not email:
            return "Input tidak valid", 400

        customer.nama = nama
        customer.email = email
        customer.no_telepon = no_telepon
        customer.alamat = alamat
        db.session.commit()
        return redirect(url_for('customer_list'))
    return render_template('customer_edit.html', customer=customer)

@app.route('/customer/hapus/<int:id>', methods=['POST'])
def customer_hapus(id):
    customer = Customer.query.get_or_404(id)
    db.session.delete(customer)
    db.session.commit()
    return redirect(url_for('customer_list'))

# ==================== CRUD KATEGORI ====================
@app.route('/kategori')
def kategori_list():
    daftar = Kategori.query.order_by(Kategori.nama.asc()).all()
    return render_template('kategori_list.html', daftar=daftar)

@app.route('/kategori/tambah', methods=['GET', 'POST'])
def kategori_tambah():
    if request.method == 'POST':
        nama = (request.form.get('nama') or '').strip()
        if not nama:
            return "Nama kategori wajib diisi", 400

        if Kategori.query.filter_by(nama=nama).first():
            return "Kategori dengan nama tersebut sudah ada", 400

        k = Kategori(nama=nama)
        db.session.add(k)
        db.session.commit()
        return redirect(url_for('kategori_list'))
    return render_template('kategori_tambah.html')

@app.route('/kategori/edit/<int:id>', methods=['GET', 'POST'])
def kategori_edit(id):
    k = Kategori.query.get_or_404(id)
    if request.method == 'POST':
        nama = (request.form.get('nama') or '').strip()
        if not nama:
            return "Nama kategori wajib diisi", 400

        ada = Kategori.query.filter(Kategori.nama == nama, Kategori.id != id).first()
        if ada:
            return "Kategori dengan nama tersebut sudah ada", 400

        k.nama = nama
        db.session.commit()
        return redirect(url_for('kategori_list'))
    return render_template('kategori_edit.html', kategori=k)

@app.route('/kategori/hapus/<int:id>', methods=['POST'])
def kategori_hapus(id):
    k = Kategori.query.get_or_404(id)
    if k.produk and len(k.produk) > 0:
        return "Kategori tidak bisa dihapus karena masih dipakai produk.", 400
    db.session.delete(k)
    db.session.commit()
    return redirect(url_for('kategori_list'))

# ==================== ROOMS (opsional multi-transaksi) ====================
@app.route('/room/new')
def room_new():
    # buat kode unik
    while True:
        kode = gen_room_code()
        if not Room.query.filter_by(kode=kode).first():
            break
    r = Room(kode=kode, status='open')
    db.session.add(r)
    db.session.commit()
    session['room_code'] = r.kode
    return redirect(url_for('index'))

@app.route('/room/switch/<kode>')
def room_switch(kode):
    r = Room.query.filter_by(kode=kode, status='open').first_or_404()
    session['room_code'] = r.kode
    return redirect(url_for('index'))

@app.route('/rooms')
def rooms_list():
    rooms_open   = Room.query.filter_by(status='open').order_by(Room.created_at.desc()).all()
    rooms_closed = Room.query.filter_by(status='closed').order_by(Room.created_at.desc()).all()
    summaries = {}
    for r in rooms_open + rooms_closed:
        total_item = db.session.query(db.func.coalesce(db.func.sum(RoomItem.jumlah), 0)) \
            .filter(RoomItem.room_id == r.id).scalar() or 0
        summaries[r.id] = total_item
    return render_template('rooms_list.html', rooms_open=rooms_open, rooms_closed=rooms_closed, summaries=summaries)

# ==================== START ====================
if __name__ == "__main__":
    app.run(debug=True)