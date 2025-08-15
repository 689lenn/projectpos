// sidebar.js

document.addEventListener('DOMContentLoaded', () => {
  const sidebarToggle = document.getElementById('sidebarToggle');
  const sidebar = document.getElementById('sidebar');

  sidebarToggle.addEventListener('click', () => {
    sidebar.classList.toggle('show');
  });

  // Tutup sidebar jika klik di luar sidebar dan tombol toggle
  document.addEventListener('click', (event) => {
    if (
      !sidebar.contains(event.target) &&
      !sidebarToggle.contains(event.target) &&
      sidebar.classList.contains('show')
    ) {
      sidebar.classList.remove('show');
    }
  });
});
