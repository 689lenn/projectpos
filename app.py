from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.sql import func
from sqlalchemy.orm import joinedload
from sqlalchemy import inspect, text
from werkzeug.utils import secure_filename
from datetime import datetime, date, timedelta
import os, secrets, string
import math

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
    harga = db.Column(db.Integer, nullable=False)                 # Harga jual utama
    hpp   = db.Column(db.Integer, nullable=False, default=0)      # HPP rata-rata
    stok  = db.Column(db.Integer, nullable=False, default=0)
    foto  = db.Column(db.String(200), nullable=True)

    # Flag manufaktur (0/1 - SQLite)
    is_manufaktur = db.Column(db.Integer, nullable=False, default=0)

    kategori_id = db.Column(db.Integer, db.ForeignKey('kategori.id'), nullable=True)
    kategori = db.relationship('Kategori', back_populates='produk')

    # Harga-harga preset opsional
    harga_list = db.relationship('ProdukHarga', backref='produk', cascade='all, delete-orphan', lazy='select')

    # == Resep Bahan ==
    # Produk ini (produk jadi) memiliki daftar bahan:
    resep_bahan = db.relationship(
        'ResepBahan',
        foreign_keys='ResepBahan.produk_id',
        back_populates='produk',
        cascade='all, delete-orphan',
        lazy='select',
        overlaps="sebagai_bahan_di,bahan"
    )
    # Produk ini (sebagai bahan) dipakai pada resep produk lain:
    sebagai_bahan_di = db.relationship(
        'ResepBahan',
        foreign_keys='ResepBahan.bahan_id',
        back_populates='bahan',
        lazy='select',
        overlaps="resep_bahan,produk"
    )

class ResepBahan(db.Model):
    __tablename__ = 'resep_bahan'
    id        = db.Column(db.Integer, primary_key=True)
    produk_id = db.Column(db.Integer, db.ForeignKey('produk.id'), nullable=False)  # produk jadi
    bahan_id  = db.Column(db.Integer, db.ForeignKey('produk.id'), nullable=False)  # bahan (juga produk)
    qty       = db.Column(db.Float, nullable=False, default=1.0)                   # jumlah bahan per 1 unit produk

    # Relasi eksplisit ke Produk
    produk = db.relationship(
        'Produk',
        foreign_keys=[produk_id],
        back_populates='resep_bahan',
        overlaps="sebagai_bahan_di,bahan"
    )
    bahan = db.relationship(
        'Produk',
        foreign_keys=[bahan_id],
        back_populates='sebagai_bahan_di',
        overlaps="resep_bahan,produk"
    )

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
    id           = db.Column(db.Integer, primary_key=True)
    tanggal      = db.Column(db.String(20), nullable=False)       # YYYY-MM-DD
    total        = db.Column(db.Integer, nullable=False, default=0)

    customer_id  = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=True)
    bayar        = db.Column(db.Integer, nullable=True, default=0)
    kembalian    = db.Column(db.Integer, nullable=True, default=0)

    # Hutang
    status       = db.Column(db.String(20), nullable=False, default='LUNAS')  # 'LUNAS' / 'HUTANG'
    sisa         = db.Column(db.Integer, nullable=False, default=0)
    jatuh_tempo  = db.Column(db.String(20), nullable=True)  # YYYY-MM-DD

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
    label     = db.Column(db.String(100), nullable=False)     # "Retail", "Grosir", "Promo"
    harga     = db.Column(db.Integer, nullable=False, default=0)
    is_default = db.Column(db.Boolean, nullable=False, default=False)

class StockMutasi(db.Model):
    __tablename__ = 'stock_mutasi'
    id          = db.Column(db.Integer, primary_key=True)
    produk_id   = db.Column(db.Integer, db.ForeignKey('produk.id'), nullable=False)
    tipe        = db.Column(db.String(10), nullable=False)  # 'IN' atau 'OUT'
    qty         = db.Column(db.Integer, nullable=False, default=0)  # positif
    tanggal     = db.Column(db.String(20), nullable=False)  # 'YYYY-MM-DD'
    catatan     = db.Column(db.String(200), nullable=True)
    referensi   = db.Column(db.String(100), nullable=True)  # misal: PO-123, Retur-xxx, dll.
    unit_cost   = db.Column(db.Integer, nullable=True)      # optional biaya per unit (untuk IN)
    stok_setelah= db.Column(db.Integer, nullable=True)      # stok setelah perubahan
    created_at  = db.Column(db.DateTime, server_default=func.now())

    produk = db.relationship('Produk')

# ========== MIGRASI RINGAN ==========
with app.app_context():
    db.create_all()
    try:
        insp = inspect(db.engine)

        # ===== Migrasi tabel transaksi =====
        cols_trx = {c['name'] for c in insp.get_columns('transaksi')}
        with db.engine.begin() as conn:
            if 'status' not in cols_trx:
                conn.execute(text(
                    "ALTER TABLE transaksi ADD COLUMN status VARCHAR(20) DEFAULT 'LUNAS'"
                ))
            if 'sisa' not in cols_trx:
                conn.execute(text(
                    "ALTER TABLE transaksi ADD COLUMN sisa INTEGER DEFAULT 0"
                ))
            if 'jatuh_tempo' not in cols_trx:
                conn.execute(text(
                    "ALTER TABLE transaksi ADD COLUMN jatuh_tempo VARCHAR(20)"
                ))

        # ===== Migrasi tabel produk =====
        cols_produk = {c['name'] for c in insp.get_columns('produk')}
        with db.engine.begin() as conn:
            if 'hpp' not in cols_produk:
                conn.execute(text("ALTER TABLE produk ADD COLUMN hpp INTEGER DEFAULT 0"))
            if 'is_manufaktur' not in cols_produk:
                # pakai INTEGER agar aman di SQLite (0/1)
                conn.execute(text("ALTER TABLE produk ADD COLUMN is_manufaktur INTEGER DEFAULT 0"))

        # ===== Pastikan tabel resep_bahan ada & punya kolom qty =====
        tables = insp.get_table_names()
        if 'resep_bahan' not in tables:
            with db.engine.begin() as conn:
                conn.execute(text('''
                    CREATE TABLE resep_bahan (
                        id INTEGER PRIMARY KEY,
                        produk_id INTEGER NOT NULL,
                        bahan_id INTEGER NOT NULL,
                        qty REAL NOT NULL DEFAULT 1.0
                    )
                '''))
        else:
            cols_rb = {c['name'] for c in insp.get_columns('resep_bahan')}
            if 'qty' not in cols_rb:
                with db.engine.begin() as conn:
                    conn.execute(text('''
                        CREATE TABLE IF NOT EXISTS resep_bahan_new (
                            id INTEGER PRIMARY KEY,
                            produk_id INTEGER NOT NULL,
                            bahan_id INTEGER NOT NULL,
                            qty REAL NOT NULL DEFAULT 1.0
                        )
                    '''))
                    try:
                        if 'jumlah_per_unit' in cols_rb:
                            conn.execute(text('''
                                INSERT INTO resep_bahan_new (id, produk_id, bahan_id, qty)
                                SELECT id, produk_id, bahan_id, CAST(jumlah_per_unit AS REAL)
                                FROM resep_bahan
                            '''))
                        else:
                            conn.execute(text('''
                                INSERT INTO resep_bahan_new (id, produk_id, bahan_id, qty)
                                SELECT id, produk_id, bahan_id, 1.0
                                FROM resep_bahan
                            '''))
                    except Exception:
                        pass

                    conn.execute(text('DROP TABLE resep_bahan'))
                    conn.execute(text('ALTER TABLE resep_bahan_new RENAME TO resep_bahan'))

    except Exception as e:
        print("INFO migrasi (abaikan jika sudah terpasang):", e)

# ========== HELPER HPP & STOK ==========
def apply_incoming_hpp(old_stock, old_hpp, in_qty, in_cost):
    try:
        old_stock = int(old_stock or 0)
        old_hpp   = int(old_hpp or 0)
        in_qty    = int(in_qty or 0)
        in_cost   = int(in_cost or 0)
    except Exception:
        return old_hpp

    denom = old_stock + in_qty
    if in_qty <= 0 or in_cost <= 0 or denom <= 0:
        return old_hpp

    try:
        new_hpp = (old_stock * old_hpp + in_qty * in_cost) // denom
        return int(new_hpp)
    except Exception:
        return old_hpp

def produce_manufactured_product(produk_id, qty, tanggal, catatan=None, referensi=None):
    """
    Produksi produk manufaktur (produk punya resep_bahan):
    - Kurangi stok bahan sesuai resep (OUT), kebutuhan = ceil(qty_produksi * qty_per_unit).
    - Tambah stok produk jadi (IN).
    - Update HPP produk jadi dengan rata-rata tertimbang dari biaya bahan.
    Return: (ok: bool, pesan: str)
    """
    # Validasi qty
    try:
        qty = int(qty or 0)
    except Exception:
        return False, "Qty produksi tidak valid."
    if qty <= 0:
        return False, "Qty produksi harus lebih dari 0."

    # Ambil produk jadi
    p = Produk.query.get_or_404(int(produk_id))

    # Resep
    resep = ResepBahan.query.filter_by(produk_id=p.id).all()
    if not resep:
        return False, "Produk ini tidak memiliki resep bahan."

    total_biaya_bahan = 0
    bahan_ops = []

    # Hitung kebutuhan dan biaya
    for r in resep:
        bahan = Produk.query.get(r.bahan_id)
        if not bahan:
            return False, f"Bahan dengan ID {r.bahan_id} tidak ditemukan."

        qty_need = qty * float(r.qty or 0.0)           # tanpa waste
        qty_need_int = int(math.ceil(qty_need))        # stok integer → ceil

        cost_per_unit = int(bahan.hpp or 0)
        biaya_bahan   = qty_need_int * cost_per_unit

        bahan_ops.append({
            "bahan": bahan,
            "qty_out": qty_need_int,
            "cost_per": cost_per_unit,
            "biaya": biaya_bahan
        })
        total_biaya_bahan += biaya_bahan

    # KURANGI BAHAN (OUT)
    for op in bahan_ops:
        b = op["bahan"]
        b.stok = int((b.stok or 0) - op["qty_out"])
        db.session.add(StockMutasi(
            produk_id=b.id,
            tipe='OUT',
            qty=op["qty_out"],
            tanggal=tanggal,
            catatan=(catatan or f"Produksi {p.nama}"),
            referensi=(referensi or f"PROD-{p.id}"),
            unit_cost=op["cost_per"],          # opsional info biaya per unit bahan
            stok_setelah=b.stok
        ))

    # TAMBAH STOK PRODUK JADI (IN) + HPP
    old_stock = int(p.stok or 0)
    old_hpp   = int(p.hpp or 0)
    p.stok = old_stock + qty

    unit_cost_finish = int(round(total_biaya_bahan / qty)) if total_biaya_bahan > 0 else old_hpp
    p.hpp = apply_incoming_hpp(old_stock, old_hpp, qty, unit_cost_finish)

    db.session.add(StockMutasi(
        produk_id=p.id,
        tipe='IN',
        qty=qty,
        tanggal=tanggal,
        catatan=(catatan or "Produksi via resep"),
        referensi=(referensi or f"PROD-{p.id}"),
        unit_cost=unit_cost_finish,
        stok_setelah=p.stok
    ))

    db.session.commit()
    return True, f"Produksi {qty} × {p.nama} berhasil. Biaya bahan total: {rupiah_filter(total_biaya_bahan)}"

def create_stock_mutasi(
    produk_id,
    tipe,                 # 'IN' atau 'OUT'
    qty,
    tanggal,              # string 'YYYY-MM-DD'
    catatan=None,
    referensi=None,
    unit_cost=None,       # harga per unit yang masuk (opsional)
    update_hpp=False      # kalau True dan tipe=='IN' → HPP ikut dihitung ulang
):
    try:
        p = Produk.query.get_or_404(int(produk_id))
    except Exception:
        return False, "Produk tidak ditemukan."

    try:
        q = max(0, int(qty or 0))
    except Exception:
        return False, "Qty tidak valid."

    if q == 0:
        return False, "Qty harus lebih dari 0."

    tipe = (tipe or '').upper().strip()
    if tipe not in ('IN', 'OUT'):
        return False, "Tipe mutasi tidak valid. Gunakan 'IN' atau 'OUT'."

    if tipe == 'IN':
        new_stok = (p.stok or 0) + q
        if update_hpp:
            try:
                uc = int(unit_cost) if unit_cost not in (None, '') else 0
            except Exception:
                uc = 0
            if uc > 0:
                p.hpp = apply_incoming_hpp(p.stok, p.hpp, q, uc)
    else:
        new_stok = (p.stok or 0) - q

    p.stok = new_stok

    try:
        unit_cost_int = int(unit_cost) if unit_cost not in (None, '') else None
    except Exception:
        unit_cost_int = None

    mut = StockMutasi(
        produk_id=p.id,
        tipe=tipe,
        qty=q,
        tanggal=tanggal,
        catatan=(catatan or '').strip() or None,
        referensi=(referensi or '').strip() or None,
        unit_cost=unit_cost_int,
        stok_setelah=new_stok
    )

    db.session.add(mut)
    db.session.commit()
    return True, "Mutasi stok tersimpan."

# ==================== UTIL & FILTER ====================
def get_default_price(produk: 'Produk'):
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

@app.template_filter("rupiah")
def rupiah_filter(n):
    try:
        return "Rp " + f"{int(n):,}".replace(",", ".")
    except Exception:
        try:
            return "Rp " + f"{float(n):,.0f}".replace(",", ".")
        except Exception:
            return f"Rp {n}"

# Jadikan global
app.jinja_env.globals['rupiah'] = rupiah_filter

def gen_room_code(n=6):
    alphabet = string.ascii_uppercase + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(n))

def ensure_room():
    return session.get('room_code')

def get_current_room():
    code = session.get('room_code')
    if not code:
        return None
    return Room.query.filter_by(kode=code, status='open').first()

def get_cart_dict_for_template():
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

@app.context_processor
def inject_globals():
    room = get_current_room()
    cart = get_cart_dict_for_template()
    count = sum(item.get("jumlah", 0) for item in cart.values())
    return {"current_room": room, "cart_count": count}

# ==================== HALAMAN UTAMA ====================
@app.route("/")
def index():
    ensure_room()
    daftar_produk   = Produk.query.all()
    daftar_kategori = Kategori.query.order_by(Kategori.nama.asc()).all()
    daftar_rooms    = Room.query.filter_by(status='open').order_by(Room.created_at.desc()).all()

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

# ==================== KERANJANG ====================
@app.route("/tambah_keranjang", methods=["POST"])
def tambah_keranjang():
    produk_id    = request.form.get("produk_id")
    harga_id     = request.form.get("harga_id")
    harga_manual = request.form.get("harga_manual")
    qty = int(request.form.get("jumlah") or request.form.get("qty") or 0)

    if not produk_id or qty <= 0:
        flash("Jumlah tidak valid.", "error")
        return redirect(url_for("index"))

    p = Produk.query.get_or_404(int(produk_id))

    snap_price = None
    if harga_manual:
        try:
            hm = int(harga_manual)
            if hm > 0:
                snap_price = hm
        except:
            pass
    if snap_price is None and harga_id and harga_id.isdigit():
        ph = ProdukHarga.query.get(int(harga_id))
        if ph and ph.produk_id == p.id:
            snap_price = ph.harga
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

    produk_hpp = {}
    for pid, item in cart.items():
        p = Produk.query.get(int(pid))
        produk_hpp[pid] = p.hpp if p and p.hpp is not None else 0

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
    room   = get_current_room()
    keys   = request.form.getlist("key[]")
    qtys   = request.form.getlist("qty[]") or request.form.getlist("jumlah[]")
    prices = request.form.getlist("price[]")

    if room:
        for key, q, h in zip(keys, qtys, prices):
            pid  = int(key)
            q_int = max(0, int(q or 0))
            h_int = max(0, int(h or 0)) if (h is not None and h != "") else None
            it = RoomItem.query.filter_by(room_id=room.id, produk_id=pid).first()
            if it:
                if q_int == 0:
                    db.session.delete(it)
                else:
                    it.jumlah = q_int
                    if h_int is not None:
                        it.harga = h_int
        db.session.commit()
    else:
        cart = session.get('cart', {})
        for key, q, h in zip(keys, qtys, prices):
            q_int = max(0, int(q or 0))
            h_int = max(0, int(h or 0)) if (h is not None and h != "") else None
            if key in cart:
                if q_int == 0:
                    cart.pop(key, None)
                else:
                    cart[key]["jumlah"] = q_int
                    if h_int is not None:
                        cart[key]["harga"] = h_int
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

@app.route("/keranjang/update_price", methods=["POST"])
def keranjang_update_price():
    key   = request.form.get("key")
    harga = request.form.get("price")

    if not key:
        flash("Item tidak ditemukan.", "error")
        return redirect(url_for("keranjang_view"))

    try:
        harga_int = max(0, int(harga or 0))
    except ValueError:
        flash("Harga tidak valid.", "error")
        return redirect(url_for("keranjang_view"))

    room = get_current_room()
    if room:
        it = RoomItem.query.filter_by(room_id=room.id, produk_id=int(key)).first()
        if it:
            it.harga = harga_int
            db.session.commit()
        else:
            flash("Item tidak ditemukan di keranjang room.", "error")
    else:
        cart = session.get('cart', {})
        if key in cart:
            cart[key]["harga"] = harga_int
            session['cart'] = cart
            session.modified = True
        else:
            flash("Item tidak ditemukan di keranjang.", "error")

    flash("Harga berhasil diperbarui.", "success")
    return redirect(url_for("keranjang_view"))

@app.route("/keranjang/clear", methods=["POST"])
def keranjang_clear():
    room = get_current_room()
    if room:
        RoomItem.query.filter_by(room_id=room.id).delete()
        room.status = 'closed'
        db.session.commit()
        session.pop('room_code', None)
    else:
        session.pop('cart', None)
        session.modified = True

    flash("Keranjang telah dibatalkan.", "info")
    return redirect(url_for("index"))

# ==================== PEMBAYARAN ====================
@app.route("/pembayaran", methods=["GET", "POST"])
def pembayaran():
    cart = get_cart_dict_for_template()
    if not cart:
        flash("Keranjang kosong.", "error")
        return redirect(url_for("keranjang_view"))

    total = sum(item["harga"] * item["jumlah"] for item in cart.values())

    if request.method == "POST":
        customer_id  = request.form.get("customer_id")
        bayar        = int(request.form.get("bayar") or 0)
        is_hutang    = request.form.get("is_hutang") == "1"
        jatuh_tempo  = (request.form.get("jatuh_tempo") or "").strip()

        if is_hutang and (not customer_id or not customer_id.isdigit()):
            flash("Transaksi hutang harus memilih pelanggan.", "error")
            return redirect(url_for("pembayaran"))

        status = 'LUNAS'
        sisa   = 0
        kembalian = 0

        if is_hutang:
            if bayar >= total:
                status = 'LUNAS'
                sisa   = 0
                kembalian = bayar - total
            else:
                status = 'HUTANG'
                sisa   = total - bayar
                kembalian = 0
        else:
            if bayar < total:
                flash("Nominal bayar kurang dari total untuk transaksi LUNAS.", "error")
                return redirect(url_for("pembayaran"))
            kembalian = bayar - total
            sisa = 0
            status = 'LUNAS'

        tgl = datetime.now().strftime("%Y-%m-%d")
        trx = Transaksi(
            tanggal=tgl,
            total=total,
            customer_id=int(customer_id) if customer_id and customer_id.isdigit() else None,
            bayar=bayar,
            kembalian=kembalian,
            status=status,
            sisa=sisa,
            jatuh_tempo=jatuh_tempo if (is_hutang and sisa > 0 and jatuh_tempo) else None
        )
        db.session.add(trx)
        db.session.flush()

        for pid, item in cart.items():
            p = Produk.query.get(int(pid))
            if not p:
                continue
            p.stok -= item["jumlah"]
            db.session.add(ItemTransaksi(transaksi_id=trx.id, produk_id=p.id, jumlah=item["jumlah"]))

        room = get_current_room()
        if room:
            room.status = 'closed'
            db.session.commit()
            session.pop('room_code', None)
        else:
            db.session.commit()

        session.pop("cart", None)

        if status == 'HUTANG':
            flash(f"Transaksi TERSIMPAN sebagai HUTANG. Sisa: {rupiah_filter(sisa)}", "success")
        else:
            flash("Transaksi LUNAS berhasil disimpan.", "success")

        return redirect(url_for("transaksi_detail", id=trx.id))

    customers = Customer.query.order_by(Customer.nama.asc()).all()
    return render_template("pembayaran.html", total=total, customers=customers)

# ==================== LAPORAN & ANALITIK ====================
def compute_laporan_periodik(start_str: str, end_str: str, status: str):
    def sisa_of(t):
        bayar = t.bayar or 0
        return max(0, (t.total or 0) - bayar)

    q = Transaksi.query.filter(
        Transaksi.tanggal >= start_str,
        Transaksi.tanggal <= end_str
    ).order_by(Transaksi.id.desc())

    trx_all = q.all()

    if status == 'hutang':
        trx_filtered = [t for t in trx_all if sisa_of(t) > 0]
    elif status == 'lunas':
        trx_filtered = [t for t in trx_all if sisa_of(t) == 0]
    else:
        trx_filtered = trx_all

    total_trx       = len(trx_filtered)
    total_penjualan = sum((t.total or 0) for t in trx_filtered)
    total_dibayar   = sum((t.bayar or 0) for t in trx_filtered)
    total_sisa      = sum(sisa_of(t) for t in trx_filtered)
    avg_ticket      = (total_penjualan / total_trx) if total_trx > 0 else 0

    total_item_terjual = 0
    for t in trx_filtered:
        for it in t.item_transaksi:
            total_item_terjual += (it.jumlah or 0)

    drill_rows = []
    for t in trx_filtered:
        sisa = sisa_of(t)
        status_lbl = "HUTANG" if sisa > 0 else "LUNAS"
        drill_rows.append({
            "id": t.id,
            "tanggal": t.tanggal,
            "customer": (t.customer.nama if t.customer else "-"),
            "total": t.total or 0,
            "bayar": t.bayar or 0,
            "sisa": sisa,
            "status": status_lbl
        })

    return {
        "total_trx": total_trx,
        "total_penjualan": total_penjualan,
        "total_dibayar": total_dibayar,
        "total_sisa": total_sisa,
        "avg_ticket": avg_ticket,
        "total_item_terjual": total_item_terjual,
        "drill_rows": drill_rows,
    }

@app.route('/laporan', endpoint='laporan_home')
def laporan_home():
    view = request.args.get('view', 'overview')

    today = date.today()
    today_s = today.strftime("%Y-%m-%d")
    last7_start = today - timedelta(days=6)
    last7_start_s = last7_start.strftime("%Y-%m-%d")
    month_start = today.replace(day=1)
    month_start_s = month_start.strftime("%Y-%m-%d")
    last30_start = today - timedelta(days=29)
    last30_start_s = last30_start.strftime("%Y-%m-%d")

    ctx = {"current_view": view}

    if view == 'overview':
        qs_today = Transaksi.query.filter(Transaksi.tanggal == today_s).order_by(Transaksi.id.desc()).all()
        omzet_today = sum((t.total or 0) for t in qs_today)
        trx_today   = len(qs_today)

        qs_last7 = Transaksi.query.filter(Transaksi.tanggal >= last7_start_s,
                                          Transaksi.tanggal <= today_s).all()
        omzet_last7 = sum((t.total or 0) for t in qs_last7)

        qs_month = Transaksi.query.filter(Transaksi.tanggal >= month_start_s,
                                          Transaksi.tanggal <= today_s).all()
        omzet_month = sum((t.total or 0) for t in qs_month)

        qs_hutang = Transaksi.query.filter(Transaksi.status == 'HUTANG').order_by(Transaksi.id.desc()).all()
        total_hutang_outstanding = sum((t.sisa or max(0, (t.total or 0) - (t.bayar or 0))) for t in qs_hutang)
        count_hutang_outstanding = sum(1 for _ in qs_hutang)

        series_labels = []
        series_values = []
        day_cursor = last7_start
        for _ in range(7):
            d_s = day_cursor.strftime("%Y-%m-%d")
            rows = Transaksi.query.filter(Transaksi.tanggal == d_s).all()
            s = sum((t.total or 0) for t in rows)
            series_labels.append(day_cursor.strftime("%d/%m"))
            series_values.append(int(s))
            day_cursor += timedelta(days=1)

        top_map = {}
        trs_30 = (Transaksi.query.filter(Transaksi.tanggal >= last30_start_s,
                                         Transaksi.tanggal <= today_s)
                  .options(joinedload(Transaksi.item_transaksi).joinedload(ItemTransaksi.produk))
                  .all())
        for t in trs_30:
            for it in t.item_transaksi:
                p = it.produk
                if not p:
                    continue
                pid = p.id
                if pid not in top_map:
                    top_map[pid] = {"nama": p.nama, "qty": 0}
                top_map[pid]["qty"] += (it.jumlah or 0)
        top_produk_30 = sorted(top_map.values(), key=lambda x: x["qty"], reverse=True)[:5]

        trx_today_rows = (Transaksi.query
                          .filter(Transaksi.tanggal == today_s)
                          .order_by(Transaksi.id.desc())
                          .options(joinedload(Transaksi.customer))
                          .all())

        hutang_terbaru = (Transaksi.query
                          .filter(Transaksi.status == 'HUTANG')
                          .order_by(Transaksi.id.desc())
                          .limit(8)
                          .options(joinedload(Transaksi.customer))
                          .all())

        ctx.update({
            "today": today,
            "omzet_today": omzet_today,
            "trx_today": trx_today,
            "omzet_last7": omzet_last7,
            "omzet_month": omzet_month,
            "total_hutang_outstanding": total_hutang_outstanding,
            "count_hutang_outstanding": count_hutang_outstanding,
            "series_labels": series_labels,
            "series_values": series_values,
            "top_produk_30": top_produk_30,
            "trx_today_rows": trx_today_rows,
            "hutang_terbaru": hutang_terbaru,
            "last7_start": last7_start,
            "month_start": month_start,
        })
        return render_template('laporan_home.html', **ctx)

    if view == 'periodik':
        default_start = (today - timedelta(days=6)).strftime("%Y-%m-%d")
        default_end   = today.strftime("%Y-%m-%d")

        start_str = request.args.get('start', default_start)
        end_str   = request.args.get('end', default_end)
        status    = request.args.get('status', 'all')  # all|lunas|hutang

        data = compute_laporan_periodik(start_str, end_str, status)
        ctx.update({
            "start": start_str,
            "end": end_str,
            "status": status,
            **data
        })
        return render_template('laporan_home.html', **ctx)

    ctx["current_view"] = "overview"
    return render_template('laporan_home.html', **ctx)

@app.route('/laporan/periodik')
def laporan_periodik_redirect():
    return redirect(url_for('laporan_home', view='periodik'))

# ==================== TRANSAKSI LIST/DETAIL ====================
@app.route('/transaksi')
def transaksi_list():
    daftar_transaksi = Transaksi.query.order_by(Transaksi.id.desc()).all()
    return render_template('transaksi_list.html', daftar_transaksi=daftar_transaksi)

@app.route('/transaksi/<int:id>')
def transaksi_detail(id):
    transaksi = (Transaksi.query
        .options(
            joinedload(Transaksi.item_transaksi).joinedload(ItemTransaksi.produk),
            joinedload(Transaksi.customer)
        )
        .get_or_404(id)
    )
    prev_url = request.args.get('prev') or request.referrer or url_for('transaksi_list')
    return render_template('transaksi_detail.html', transaksi=transaksi, prev_url=prev_url)

# ==================== CRUD PRODUK ====================
def to_float(val):
    try:
        return float((val or '').replace(',', '.').strip())
    except Exception:
        return 0.0

@app.route('/produk')
def produk_list():
    daftar_produk = Produk.query.all()
    return render_template('produk_list.html', daftar_produk=daftar_produk)

@app.route('/produk/tambah', methods=['GET', 'POST'])
def produk_tambah():
    if request.method == 'POST':
        nama  = (request.form.get('nama') or '').strip()
        harga_utama = request.form.get('harga') or '0'
        hpp   = request.form.get('hpp') or '0'
        stok  = request.form.get('stok') or '0'
        kategori_id = request.form.get('kategori_id')
        is_manufaktur = 1 if request.form.get('is_manufaktur') == '1' else 0

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
            hpp=int(hpp),
            stok=int(stok),
            foto=foto_filename,
            kategori_id=int(kategori_id) if kategori_id and kategori_id.isdigit() else None,
            is_manufaktur=is_manufaktur
        )
        db.session.add(p)
        db.session.flush()  # dapat p.id

        # Harga tambahan (opsional)
        labels = request.form.getlist('harga_label[]')
        values = request.form.getlist('harga_value[]')
        default_key = request.form.get('harga_default')
        for i, (lbl, val) in enumerate(zip(labels, values)):
            lbl = (lbl or '').strip()
            v = int(val or 0)
            if not lbl or v <= 0:
                continue
            is_def = (default_key == f'row-{i}')
            db.session.add(ProdukHarga(produk_id=p.id, label=lbl, harga=v, is_default=is_def))

        # Resep (jika manufaktur)
        if is_manufaktur == 1:
            bahan_ids  = request.form.getlist('bahan_id[]')
            bahan_qtys = request.form.getlist('bahan_qty[]')
            for bid, q in zip(bahan_ids, bahan_qtys):
                if not bid:
                    continue
                try:
                    bahan_id = int(bid)
                except:
                    continue
                qty = to_float(q)
                if bahan_id == p.id or qty <= 0:
                    continue
                db.session.add(ResepBahan(produk_id=p.id, bahan_id=bahan_id, qty=qty))

        db.session.commit()
        return redirect(url_for('produk_list'))

    kategori = Kategori.query.order_by(Kategori.nama.asc()).all()
    semua_produk = Produk.query.order_by(Produk.nama.asc()).all()
    return render_template('tambah_produk.html', kategori=kategori, semua_produk=semua_produk)

@app.route('/produk/edit/<int:id>', methods=['GET', 'POST'])
def produk_edit(id):
    produk = Produk.query.get_or_404(id)
    if request.method == 'POST':
        nama  = (request.form.get('nama') or '').strip()
        harga_utama = request.form.get('harga') or '0'
        hpp   = request.form.get('hpp') or '0'
        stok  = request.form.get('stok') or '0'
        kategori_id = request.form.get('kategori_id')
        is_manufaktur = 1 if request.form.get('is_manufaktur') == '1' else 0

        if not nama or not harga_utama.isdigit() or not stok.isdigit() or not hpp.isdigit():
            return "Input tidak valid", 400

        produk.nama  = nama
        produk.harga = int(harga_utama)
        produk.hpp   = int(hpp)
        produk.stok  = int(stok)
        produk.kategori_id = int(kategori_id) if kategori_id and kategori_id.isdigit() else None
        produk.is_manufaktur = is_manufaktur

        foto_file = request.files.get('foto')
        if foto_file and foto_file.filename:
            foto_filename = secure_filename(foto_file.filename)
            foto_file.save(os.path.join(app.config['UPLOAD_FOLDER'], foto_filename))
            produk.foto = foto_filename

        # Reset resep & simpan ulang jika manufaktur
        for r in list(produk.resep_bahan):
            db.session.delete(r)

        if is_manufaktur == 1:
            bahan_ids  = request.form.getlist('bahan_id[]')
            bahan_qtys = request.form.getlist('bahan_qty[]')
            for bid, q in zip(bahan_ids, bahan_qtys):
                if not bid:
                    continue
                try:
                    bahan_id = int(bid)
                except:
                    continue
                qty = to_float(q)
                if bahan_id == produk.id or qty <= 0:
                    continue
                db.session.add(ResepBahan(produk_id=produk.id, bahan_id=bahan_id, qty=qty))

        db.session.commit()
        return redirect(url_for('produk_list'))

    kategori = Kategori.query.order_by(Kategori.nama.asc()).all()
    semua_produk = Produk.query.filter(Produk.id != produk.id).order_by(Produk.nama.asc()).all()
    return render_template('produk_edit.html', produk=produk, kategori=kategori, semua_produk=semua_produk)

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

        c = Customer(nama=nama, email=email, no_telepon=no_telepon, alamat=alamat)
        db.session.add(c)
        db.session.commit()
        return redirect(url_for('customer_list'))
    return render_template('customer_tambah.html')

@app.route('/customer/edit/<int:id>', methods=['GET', 'POST'])
def customer_edit(id):
    c = Customer.query.get_or_404(id)
    if request.method == 'POST':
        nama = (request.form.get('nama') or '').strip()
        email = (request.form.get('email') or '').strip()
        no_telepon = request.form.get('no_telepon')
        alamat     = request.form.get('alamat')

        if not nama or not email:
            return "Input tidak valid", 400  # <- PERBAIKAN: gunakan 'or' (bukan 'atau')

        c.nama = nama
        c.email = email
        c.no_telepon = no_telepon
        c.alamat = alamat
        db.session.commit()
        return redirect(url_for('customer_list'))
    return render_template('customer_edit.html', customer=c)

@app.route('/customer/hapus/<int:id>', methods=['POST'])
def customer_hapus(id):
    c = Customer.query.get_or_404(id)
    db.session.delete(c)
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

# ============== STOK DASHBOARD ==============
@app.route('/stok')
def stok_dashboard():
    daftar_produk = Produk.query.order_by(Produk.nama.asc()).all()
    today = date.today().strftime("%Y-%m-%d")
    return render_template('stok_dashboard.html', daftar_produk=daftar_produk, today=today)

@app.route('/stok/adjust', methods=['POST'])
def stok_adjust():
    produk_id = request.form.get('produk_id')
    tipe      = request.form.get('tipe')           # 'IN' atau 'OUT'
    qty       = request.form.get('qty')
    tanggal   = request.form.get('tanggal') or date.today().strftime("%Y-%m-%d")
    catatan   = request.form.get('catatan')
    referensi = request.form.get('referensi')
    unit_cost = request.form.get('unit_cost')      # optional untuk IN
    update_hpp= (request.form.get('update_hpp') == '1')

    if not produk_id or tipe not in ('IN','OUT'):
        flash("Input tidak lengkap.", "error")
        return redirect(url_for('stok_dashboard'))

    # Cek apakah produk manufaktur (punya resep)
    p = Produk.query.get(int(produk_id))
    if not p:
        flash("Produk tidak ditemukan.", "error")
        return redirect(url_for('stok_dashboard'))

    # Jika TAMBAH STOK untuk produk yang punya resep → PRODUKSI OTOMATIS
    has_recipe = ResepBahan.query.filter_by(produk_id=p.id).count() > 0
    if tipe == 'IN' and has_recipe:
        ok, msg = produce_manufactured_product(
            produk_id=p.id,
            qty=qty,
            tanggal=tanggal,
            catatan=catatan,
            referensi=referensi
        )
        flash(msg, "success" if ok else "error")
        return redirect(url_for('stok_dashboard'))

    # Selain itu, jalur normal (produk biasa / OUT bahan / IN tanpa resep)
    ok, msg = create_stock_mutasi(
        produk_id=produk_id, tipe=tipe, qty=qty, tanggal=tanggal,
        catatan=catatan, referensi=referensi, unit_cost=unit_cost, update_hpp=update_hpp
    )
    flash(msg, "success" if ok else "error")
    return redirect(url_for('stok_dashboard'))

# ============== LAPORAN MUTASI STOK ==============
@app.route('/stok/mutasi')
def stok_mutasi_list():
    start = (request.args.get('start') or '').strip()
    end   = (request.args.get('end') or '').strip()
    pid   = (request.args.get('produk_id') or '').strip()
    tipe  = (request.args.get('tipe') or '').strip().upper()  # '', 'IN', 'OUT'

    q = StockMutasi.query.order_by(StockMutasi.id.desc())

    if start:
        q = q.filter(StockMutasi.tanggal >= start)
    if end:
        q = q.filter(StockMutasi.tanggal <= end)
    if pid.isdigit():
        q = q.filter(StockMutasi.produk_id == int(pid))
    if tipe in ('IN', 'OUT'):
        q = q.filter(StockMutasi.tipe == tipe)

    rows = q.all()
    produk_all = Produk.query.order_by(Produk.nama.asc()).all()
    today = date.today().strftime("%Y-%m-%d")

    total_in  = sum(r.qty for r in rows if r.tipe == 'IN')
    total_out = sum(r.qty for r in rows if r.tipe == 'OUT')

    return render_template(
        'stok_mutasi.html',
        rows=rows, produk_all=produk_all, today=today,
        start=start, end=end, produk_id=pid, tipe=tipe,
        total_in=total_in, total_out=total_out
    )

# ==================== ROOMS (opsional) ====================
@app.route('/room/new')
def room_new():
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
    port = int(os.environ.get("PORT", 5003))
    app.run(host="0.0.0.0", port=port, debug=False)