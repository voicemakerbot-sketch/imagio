"""Admin panel HTML templates — login page and main dashboard with sidebar."""

from string import Template
from typing import Optional

# ═══════════════════════════════════════════════════════════════
# LOGIN PAGE
# ═══════════════════════════════════════════════════════════════

ADMIN_LOGIN_TEMPLATE = Template("""<!DOCTYPE html>
<html lang="uk">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Imagio Admin — Login</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Segoe UI',Tahoma,Geneva,Verdana,sans-serif;background:linear-gradient(135deg,#0f0c29 0%,#302b63 50%,#24243e 100%);min-height:100vh;display:flex;align-items:center;justify-content:center}
.login-card{background:rgba(255,255,255,0.97);padding:44px 36px;border-radius:18px;box-shadow:0 20px 60px rgba(0,0,0,0.35);width:100%;max-width:400px;text-align:center}
.login-card h1{color:#1e1e2f;margin-bottom:6px;font-size:26px}
.login-card p{color:#666;margin-bottom:28px;font-size:14px}
input[type=password]{width:100%;padding:14px 16px;border-radius:10px;border:1.5px solid #d0d0d8;font-size:15px;margin-bottom:18px;outline:none;transition:border .2s}
input[type=password]:focus{border-color:#667eea}
button{width:100%;padding:14px;border:none;border-radius:10px;background:linear-gradient(135deg,#667eea,#764ba2);color:#fff;font-size:15px;font-weight:600;cursor:pointer;transition:opacity .2s}
button:hover{opacity:.9}
.error{color:#e74c3c;margin-bottom:14px;font-size:14px}
</style>
</head>
<body>
<form class="login-card" method="post" action="/admin/login">
<h1>🎨 Imagio Admin</h1>
<p>Введіть пароль для доступу до панелі</p>
$error_block
<input type="password" name="password" placeholder="Пароль" required autofocus>
<button type="submit">Увійти</button>
</form>
</body>
</html>""")


def render_login_page(error: Optional[str] = None) -> str:
    error_block = f'<div class="error">{error}</div>' if error else ""
    return ADMIN_LOGIN_TEMPLATE.substitute(error_block=error_block)


# ═══════════════════════════════════════════════════════════════
# MAIN ADMIN DASHBOARD  (sidebar layout)
# ═══════════════════════════════════════════════════════════════

ADMIN_HTML = r"""<!DOCTYPE html>
<html lang="uk">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Imagio — База даних</title>
<style>
/* ── Reset & Base ─────────────────────────────────────── */
*{margin:0;padding:0;box-sizing:border-box}
:root{
  --sidebar-w:260px;
  --accent:#667eea;
  --accent2:#764ba2;
  --bg:#f0f2f5;
  --card:#fff;
  --text:#1e1e2f;
  --muted:#6b7280;
  --border:#e5e7eb;
  --success:#10b981;
  --warning:#f59e0b;
  --danger:#ef4444;
  --radius:12px;
}
body{font-family:'Segoe UI',Tahoma,Geneva,Verdana,sans-serif;background:var(--bg);color:var(--text);display:flex;min-height:100vh}

/* ── Sidebar ──────────────────────────────────────────── */
.sidebar{
  width:var(--sidebar-w);min-height:100vh;background:linear-gradient(180deg,#1e1e2f 0%,#302b63 100%);
  color:#fff;display:flex;flex-direction:column;position:fixed;left:0;top:0;z-index:100;
  transition:transform .3s ease;
}
.sidebar-header{padding:28px 22px 18px;border-bottom:1px solid rgba(255,255,255,.1)}
.sidebar-header h1{font-size:22px;font-weight:700;letter-spacing:.5px}
.sidebar-header small{color:rgba(255,255,255,.55);font-size:12px;display:block;margin-top:4px}
.sidebar-nav{flex:1;padding:12px 0}
.nav-item{
  display:flex;align-items:center;gap:12px;padding:13px 24px;cursor:pointer;
  font-size:14px;font-weight:500;color:rgba(255,255,255,.7);transition:all .15s;border-left:3px solid transparent;
}
.nav-item:hover{background:rgba(255,255,255,.08);color:#fff}
.nav-item.active{background:rgba(102,126,234,.25);color:#fff;border-left-color:var(--accent)}
.nav-item .icon{font-size:18px;width:24px;text-align:center}
.sidebar-footer{padding:18px 22px;border-top:1px solid rgba(255,255,255,.1);font-size:12px;color:rgba(255,255,255,.4)}

/* ── Main area ────────────────────────────────────────── */
.main{margin-left:var(--sidebar-w);flex:1;padding:28px 32px;min-width:0}
.top-bar{display:flex;justify-content:space-between;align-items:center;margin-bottom:24px}
.top-bar h2{font-size:22px;font-weight:700;color:var(--text)}
.btn-logout{
  padding:9px 20px;border-radius:8px;border:none;background:var(--danger);
  color:#fff;font-weight:600;font-size:13px;cursor:pointer;transition:opacity .2s
}
.btn-logout:hover{opacity:.85}

/* ── Stats cards ──────────────────────────────────────── */
.stats-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:16px;margin-bottom:28px}
.stat-card{
  background:var(--card);border-radius:var(--radius);padding:20px;
  box-shadow:0 1px 3px rgba(0,0,0,.06);display:flex;flex-direction:column;gap:4px
}
.stat-card .label{font-size:12px;color:var(--muted);text-transform:uppercase;font-weight:600;letter-spacing:.4px}
.stat-card .value{font-size:28px;font-weight:700;color:var(--text)}
.stat-card .sub{font-size:11px;color:var(--muted)}

/* ── Section (tab content) ────────────────────────────── */
.section{display:none}
.section.active{display:block}
.section-card{background:var(--card);border-radius:var(--radius);padding:24px;box-shadow:0 1px 3px rgba(0,0,0,.06)}

/* ── Search bar ───────────────────────────────────────── */
.toolbar{display:flex;gap:10px;margin-bottom:18px;flex-wrap:wrap;align-items:center}
.toolbar input,.toolbar select{
  padding:10px 14px;border:1.5px solid var(--border);border-radius:8px;font-size:14px;outline:none;transition:border .2s
}
.toolbar input:focus,.toolbar select:focus{border-color:var(--accent)}
.toolbar input{flex:1;min-width:200px}
.btn{
  padding:10px 18px;border:none;border-radius:8px;font-size:13px;font-weight:600;cursor:pointer;transition:all .15s
}
.btn-primary{background:var(--accent);color:#fff}
.btn-primary:hover{opacity:.9}
.btn-success{background:var(--success);color:#fff}
.btn-success:hover{opacity:.9}
.btn-secondary{background:#e5e7eb;color:var(--text)}
.btn-secondary:hover{background:#d1d5db}

/* ── Table ────────────────────────────────────────────── */
.table-wrap{width:100%;overflow-x:auto;margin-top:4px}
table{width:100%;border-collapse:collapse;min-width:900px}
th{background:#f9fafb;padding:12px 14px;text-align:left;font-size:12px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.3px;border-bottom:2px solid var(--border);white-space:nowrap;cursor:pointer;user-select:none}
th:hover{color:var(--accent)}
td{padding:11px 14px;border-bottom:1px solid var(--border);font-size:13px;white-space:nowrap}
tr:hover{background:#f9fafb}

.badge{display:inline-block;padding:3px 10px;border-radius:20px;font-size:11px;font-weight:600}
.badge-active{background:#d1fae5;color:#065f46}
.badge-expired{background:#fee2e2;color:#991b1b}
.badge-pending{background:#fef3c7;color:#92400e}
.badge-free{background:#e0e7ff;color:#3730a3}
.badge-inactive{background:#f3f4f6;color:#6b7280}
.badge-premium{background:#ede9fe;color:#5b21b6}

.user-link{color:var(--accent);text-decoration:none;font-weight:600}
.user-link:hover{text-decoration:underline}

/* ── Pagination ───────────────────────────────────────── */
.pagination{display:flex;justify-content:center;align-items:center;gap:8px;margin-top:18px}
.pagination button{
  padding:7px 14px;border:1.5px solid var(--border);border-radius:6px;background:#fff;
  font-size:13px;cursor:pointer;transition:all .15s
}
.pagination button:hover{border-color:var(--accent);color:var(--accent)}
.pagination button.active{background:var(--accent);color:#fff;border-color:var(--accent)}
.pagination button:disabled{opacity:.4;cursor:not-allowed}
.pagination .info{font-size:13px;color:var(--muted)}

/* ── Modal ────────────────────────────────────────────── */
.modal-overlay{
  display:none;position:fixed;inset:0;background:rgba(0,0,0,.55);z-index:999;
  align-items:center;justify-content:center
}
.modal-overlay.active{display:flex}
.modal{
  background:var(--card);border-radius:14px;padding:32px;width:94%;max-width:600px;
  max-height:90vh;overflow-y:auto;box-shadow:0 25px 60px rgba(0,0,0,.3);position:relative
}
.modal h3{font-size:18px;margin-bottom:20px;padding-right:30px}
.modal-close{position:absolute;top:16px;right:20px;font-size:22px;cursor:pointer;color:var(--muted);background:none;border:none}
.form-group{margin-bottom:14px}
.form-group label{display:block;margin-bottom:5px;font-weight:600;font-size:13px;color:var(--muted)}
.form-group input,.form-group select,.form-group textarea{
  width:100%;padding:10px 12px;border:1.5px solid var(--border);border-radius:8px;font-size:14px;outline:none
}
.form-group input:focus,.form-group select:focus,.form-group textarea:focus{border-color:var(--accent)}
.form-actions{display:flex;gap:10px;margin-top:20px}
.form-actions .btn{flex:1}

/* ── Spinner / loading ────────────────────────────────── */
.loading{text-align:center;padding:40px;color:var(--muted)}
.spinner{border:3px solid #e5e7eb;border-top:3px solid var(--accent);border-radius:50%;width:28px;height:28px;animation:spin .8s linear infinite;margin:0 auto 10px}
@keyframes spin{to{transform:rotate(360deg)}}

/* ── Mobile hamburger ─────────────────────────────────── */
.hamburger{display:none;position:fixed;top:16px;left:16px;z-index:200;background:var(--accent);border:none;border-radius:8px;padding:10px 12px;cursor:pointer;color:#fff;font-size:20px}
@media(max-width:900px){
  .sidebar{transform:translateX(-100%)}
  .sidebar.open{transform:translateX(0)}
  .main{margin-left:0;padding:20px 16px;padding-top:60px}
  .hamburger{display:block}
  .stats-grid{grid-template-columns:repeat(2,1fr)}
}
@media(max-width:560px){
  .stats-grid{grid-template-columns:1fr}
  .toolbar{flex-direction:column}
  .toolbar input,.toolbar select,.toolbar .btn{width:100%}
}

/* ── Toast ────────────────────────────────────────────── */
.toast{position:fixed;bottom:24px;right:24px;padding:14px 22px;border-radius:10px;color:#fff;font-size:14px;font-weight:600;z-index:9999;opacity:0;transform:translateY(20px);transition:all .3s}
.toast.show{opacity:1;transform:translateY(0)}
.toast-success{background:var(--success)}
.toast-error{background:var(--danger)}
</style>
</head>
<body>

<!-- Hamburger (mobile) -->
<button class="hamburger" onclick="document.querySelector('.sidebar').classList.toggle('open')">☰</button>

<!-- ═══ SIDEBAR ═══ -->
<aside class="sidebar" id="sidebar">
  <div class="sidebar-header">
    <h1>🎨 Imagio</h1>
    <small>База даних</small>
  </div>
  <nav class="sidebar-nav">
    <div class="nav-item active" data-section="users" onclick="switchSection('users')">
      <span class="icon">👥</span> Користувачі
    </div>
    <div class="nav-item" data-section="broadcasts" onclick="switchSection('broadcasts')">
      <span class="icon">📢</span> Розсилки
    </div>
    <div class="nav-item" data-section="promos" onclick="switchSection('promos')">
      <span class="icon">🎟️</span> Промокоди
    </div>
    <div class="nav-item" data-section="payments" onclick="switchSection('payments')">
      <span class="icon">💳</span> Оплати
    </div>
    <div class="nav-item" data-section="partners" onclick="switchSection('partners')">
      <span class="icon">🤝</span> Партнери
    </div>
    <div class="nav-item" data-section="logs" onclick="switchSection('logs')">
      <span class="icon">📋</span> Логи
    </div>
  </nav>
  <div class="sidebar-footer">Imagio Admin v1.0</div>
</aside>

<!-- ═══ MAIN CONTENT ═══ -->
<div class="main">

  <!-- Top bar -->
  <div class="top-bar">
    <h2 id="sectionTitle">👥 Користувачі</h2>
    <button class="btn-logout" onclick="logout()">Вийти</button>
  </div>

  <!-- Stats -->
  <div class="stats-grid" id="statsGrid">
    <div class="stat-card"><div class="label">Всього користувачів</div><div class="value" id="statTotal">—</div></div>
    <div class="stat-card"><div class="label">Активні (7 днів)</div><div class="value" id="statActive">—</div></div>
    <div class="stat-card"><div class="label">Платні (Premium+Pro)</div><div class="value" id="statPremium">—</div></div>
    <div class="stat-card"><div class="label">Frozen</div><div class="value" id="statFrozen">—</div></div>
    <div class="stat-card"><div class="label">Успішних платежів</div><div class="value" id="statPayments">—</div></div>
    <div class="stat-card"><div class="label">Дохід ($)</div><div class="value" id="statRevenue">—</div></div>
    <div class="stat-card"><div class="label">Генерацій (всього)</div><div class="value" id="statGenerations">—</div></div>
  </div>

  <!-- ═══ SECTION: USERS ═══ -->
  <div class="section active" id="sec-users">
    <div class="section-card">
      <div class="toolbar">
        <input type="text" id="userSearch" placeholder="Пошук за ID, username, ім'ям…" onkeydown="if(event.key==='Enter')loadUsers()">
        <select id="userStatusFilter" onchange="loadUsers()">
          <option value="">Всі статуси</option>
          <option value="free">Free</option>
          <option value="premium">Premium</option>
          <option value="pro">Pro</option>
          <option value="frozen">Frozen</option>
        </select>
        <button class="btn btn-primary" onclick="loadUsers()">🔍 Шукати</button>
        <button class="btn btn-success" onclick="exportUsersCSV()">📥 CSV</button>
      </div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th onclick="sortUsers('telegram_id')">ID ↕</th>
              <th onclick="sortUsers('username')">Username ↕</th>
              <th onclick="sortUsers('subscription_tier')">Статус ↕</th>
              <th onclick="sortUsers('sub_expires')">Діє до ↕</th>
              <th onclick="sortUsers('created_at')">Створено ↕</th>
              <th>Дії</th>
            </tr>
          </thead>
          <tbody id="usersTableBody">
            <tr><td colspan="6" class="loading"><div class="spinner"></div>Завантаження…</td></tr>
          </tbody>
        </table>
      </div>
      <div class="pagination" id="usersPagination"></div>
    </div>
  </div>

  <!-- ═══ SECTION: BROADCASTS (stub) ═══ -->
  <div class="section" id="sec-broadcasts">
    <div class="section-card">
      <p style="color:var(--muted);text-align:center;padding:40px">🚧 Розсилки — скоро буде…</p>
    </div>
  </div>

  <!-- ═══ SECTION: PROMOS (stub) ═══ -->
  <div class="section" id="sec-promos">
    <div class="section-card">
      <p style="color:var(--muted);text-align:center;padding:40px">🚧 Промокоди — скоро буде…</p>
    </div>
  </div>

  <!-- ═══ SECTION: PAYMENTS ═══ -->
  <div class="section" id="sec-payments">
    <div class="section-card" style="margin-bottom:20px">
      <h4 style="margin-bottom:14px">📋 Плани підписки</h4>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>ID</th>
              <th>Назва</th>
              <th>Ціна</th>
              <th>Тип</th>
              <th>Період</th>
              <th>Статус</th>
              <th>Дії</th>
            </tr>
          </thead>
          <tbody id="plansTableBody">
            <tr><td colspan="7" class="loading"><div class="spinner"></div>Завантаження…</td></tr>
          </tbody>
        </table>
      </div>
    </div>
    <div class="section-card">
      <div class="toolbar">
        <input type="text" id="paymentSearch" placeholder="Пошук за order reference, картка…" onkeydown="if(event.key==='Enter')loadPayments()">
        <select id="paymentStatusFilter" onchange="loadPayments()">
          <option value="">Всі статуси</option>
          <option value="pending">Pending</option>
          <option value="approved">Approved</option>
          <option value="declined">Declined</option>
          <option value="refunded">Refunded</option>
        </select>
        <button class="btn btn-primary" onclick="loadPayments()">🔍 Шукати</button>
      </div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Order Ref</th>
              <th>Користувач</th>
              <th>Сума</th>
              <th>План</th>
              <th>Статус</th>
              <th>Картка</th>
              <th>Дата</th>
            </tr>
          </thead>
          <tbody id="paymentsTableBody">
            <tr><td colspan="7" class="loading"><div class="spinner"></div>Завантаження…</td></tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>

  <!-- ═══ SECTION: PARTNERS (stub) ═══ -->
  <div class="section" id="sec-partners">
    <div class="section-card">
      <p style="color:var(--muted);text-align:center;padding:40px">🚧 Партнери — скоро буде…</p>
    </div>
  </div>

  <!-- ═══ SECTION: LOGS (stub) ═══ -->
  <div class="section" id="sec-logs">
    <div class="section-card">
      <p style="color:var(--muted);text-align:center;padding:40px">🚧 Логи — скоро буде…</p>
    </div>
  </div>

</div><!-- /main -->

<!-- ═══ USER DETAIL MODAL ═══ -->
<div class="modal-overlay" id="userModal">
  <div class="modal">
    <button class="modal-close" onclick="closeUserModal()">&times;</button>
    <h3 id="modalTitle">Інформація про користувача</h3>
    <div id="modalBody"></div>
  </div>
</div>

<!-- ═══ EDIT USER MODAL ═══ -->
<div class="modal-overlay" id="editUserModal">
  <div class="modal">
    <button class="modal-close" onclick="closeEditModal()">&times;</button>
    <h3>Редагувати користувача</h3>
    <div id="editModalBody"></div>
  </div>
</div>

<!-- Toast -->
<div class="toast" id="toast"></div>

<script>
/* ──────────────────────────────────────────────────────────
   STATE
   ────────────────────────────────────────────────────────── */
let allUsers = [];
let filteredUsers = [];
let currentPage = 1;
const PAGE_SIZE = 25;
let sortField = 'created_at';
let sortAsc = false;

const SECTION_TITLES = {
  users: '👥 Користувачі',
  broadcasts: '📢 Розсилки',
  promos: '🎟️ Промокоди',
  payments: '💳 Оплати',
  partners: '🤝 Партнери',
  logs: '📋 Логи'
};

/* ──────────────────────────────────────────────────────────
   NAVIGATION
   ────────────────────────────────────────────────────────── */
function switchSection(name) {
  document.querySelectorAll('.section').forEach(s => s.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
  const sec = document.getElementById('sec-' + name);
  if (sec) sec.classList.add('active');
  const nav = document.querySelector(`.nav-item[data-section="${name}"]`);
  if (nav) nav.classList.add('active');
  document.getElementById('sectionTitle').textContent = SECTION_TITLES[name] || name;
  // close sidebar on mobile
  document.querySelector('.sidebar').classList.remove('open');
  // lazy-load section data
  if (name === 'payments') { loadPlans(); loadPayments(); }
}

/* ──────────────────────────────────────────────────────────
   AUTH
   ────────────────────────────────────────────────────────── */
async function logout() {
  await fetch('/admin/logout', {method:'POST'});
  location.href = '/admin';
}

/* ──────────────────────────────────────────────────────────
   TOAST
   ────────────────────────────────────────────────────────── */
function showToast(msg, type='success') {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.className = 'toast toast-' + type + ' show';
  setTimeout(() => t.classList.remove('show'), 3000);
}

/* ──────────────────────────────────────────────────────────
   STATS
   ────────────────────────────────────────────────────────── */
async function loadStats() {
  try {
    const r = await fetch('/admin/api/stats');
    if (!r.ok) throw new Error('stats fetch failed');
    const d = await r.json();
    document.getElementById('statTotal').textContent = d.total_users ?? '—';
    document.getElementById('statActive').textContent = d.active_7d ?? '—';
    document.getElementById('statPremium').textContent = d.premium_users ?? '—';
    document.getElementById('statFrozen').textContent = d.frozen_users ?? '0';
    document.getElementById('statPayments').textContent = d.successful_payments ?? '—';
    document.getElementById('statRevenue').textContent = d.total_revenue ?? '0';
    document.getElementById('statGenerations').textContent = d.total_generations ?? '—';
  } catch(e) {
    console.error('Stats error:', e);
  }
}

/* ──────────────────────────────────────────────────────────
   USERS — LOAD
   ────────────────────────────────────────────────────────── */
async function loadUsers() {
  const search = document.getElementById('userSearch').value.trim();
  const status = document.getElementById('userStatusFilter').value;
  const params = new URLSearchParams();
  if (search) params.set('search', search);
  if (status) params.set('status', status);

  document.getElementById('usersTableBody').innerHTML = '<tr><td colspan="6" class="loading"><div class="spinner"></div>Завантаження…</td></tr>';

  try {
    const r = await fetch('/admin/api/users?' + params);
    if (!r.ok) throw new Error('users fetch failed');
    allUsers = await r.json();
    filteredUsers = [...allUsers];
    currentPage = 1;
    applySortAndRender();
  } catch(e) {
    console.error('Users error:', e);
    document.getElementById('usersTableBody').innerHTML = '<tr><td colspan="6" style="color:var(--danger);text-align:center;padding:20px">Помилка завантаження</td></tr>';
  }
}

/* ──────────────────────────────────────────────────────────
   USERS — SORT
   ────────────────────────────────────────────────────────── */
function sortUsers(field) {
  if (sortField === field) { sortAsc = !sortAsc; } else { sortField = field; sortAsc = true; }
  applySortAndRender();
}

function applySortAndRender() {
  filteredUsers.sort((a, b) => {
    let va = a[sortField] ?? '', vb = b[sortField] ?? '';
    if (typeof va === 'string') va = va.toLowerCase();
    if (typeof vb === 'string') vb = vb.toLowerCase();
    if (va < vb) return sortAsc ? -1 : 1;
    if (va > vb) return sortAsc ? 1 : -1;
    return 0;
  });
  renderUsersPage();
}

/* ──────────────────────────────────────────────────────────
   USERS — RENDER
   ────────────────────────────────────────────────────────── */
function renderUsersPage() {
  const tbody = document.getElementById('usersTableBody');
  const total = filteredUsers.length;
  const pages = Math.ceil(total / PAGE_SIZE) || 1;
  if (currentPage > pages) currentPage = pages;
  const start = (currentPage - 1) * PAGE_SIZE;
  const slice = filteredUsers.slice(start, start + PAGE_SIZE);

  if (!slice.length) {
    tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;padding:24px;color:var(--muted)">Користувачів не знайдено</td></tr>';
    document.getElementById('usersPagination').innerHTML = '';
    return;
  }

  tbody.innerHTML = slice.map(u => {
    const tierBadge = getTierBadge(u);
    const created = u.created_at ? new Date(u.created_at).toLocaleDateString('uk-UA') : '—';
    const expires = u.sub_expires ? new Date(u.sub_expires).toLocaleDateString('uk-UA') : '—';
    return `<tr>
      <td><span class="user-link" onclick="showUserDetail(${u.id})">${u.telegram_id}</span></td>
      <td>${u.username ? '@' + esc(u.username) : '<span style="color:var(--muted)">—</span>'}</td>
      <td>${tierBadge}</td>
      <td>${expires}</td>
      <td>${created}</td>
      <td>
        <button class="btn btn-primary" style="padding:5px 10px;font-size:12px" onclick="showUserDetail(${u.id})" title="Деталі">👁️</button>
        <button class="btn btn-secondary" style="padding:5px 10px;font-size:12px" onclick="openEditUser(${u.id})" title="Редагувати">✏️</button>
        <button class="btn btn-secondary" style="padding:5px 10px;font-size:12px;background:#ede9fe;color:#5b21b6" onclick="showUserPresets(${u.id})" title="Пресети">⚙️</button>
      </td>
    </tr>`;
  }).join('');

  // Pagination
  const pg = document.getElementById('usersPagination');
  let html = `<span class="info">${total} записів — стор. ${currentPage}/${pages}</span>`;
  html += `<button ${currentPage<=1?'disabled':''} onclick="goPage(${currentPage-1})">←</button>`;
  for (let i = 1; i <= pages && i <= 7; i++) {
    html += `<button class="${i===currentPage?'active':''}" onclick="goPage(${i})">${i}</button>`;
  }
  if (pages > 7) html += `<span>…</span><button onclick="goPage(${pages})">${pages}</button>`;
  html += `<button ${currentPage>=pages?'disabled':''} onclick="goPage(${currentPage+1})">→</button>`;
  pg.innerHTML = html;
}

function goPage(p) { currentPage = p; renderUsersPage(); }

function getTierBadge(u) {
  const t = u.subscription_tier || 'free';
  const map = {free:'badge-free',premium:'badge-premium',pro:'badge-active',frozen:'badge-expired'};
  const labels = {free:'Free',premium:'Premium',pro:'Pro',frozen:'Frozen'};
  const cls = map[t] || 'badge-inactive';
  return `<span class="badge ${cls}">${labels[t] || t}</span>`;
}

function esc(s) { if(!s) return ''; const d=document.createElement('div'); d.textContent=s; return d.innerHTML; }

/* ──────────────────────────────────────────────────────────
   USER DETAIL MODAL
   ────────────────────────────────────────────────────────── */
async function showUserDetail(id) {
  document.getElementById('modalBody').innerHTML = '<div class="loading"><div class="spinner"></div></div>';
  document.getElementById('userModal').classList.add('active');
  try {
    const r = await fetch('/admin/api/users/' + id);
    if (!r.ok) throw new Error();
    const u = await r.json();
    document.getElementById('modalTitle').textContent = (u.username ? '@' + u.username : 'User') + ' — деталі';
    document.getElementById('modalBody').innerHTML = `
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;font-size:14px">
        <div><strong>Telegram ID:</strong> ${u.telegram_id}</div>
        <div><strong>Username:</strong> ${u.username ? '@'+esc(u.username) : '—'}</div>
        <div><strong>Мова:</strong> ${esc(u.language)}</div>
        <div><strong>Статус:</strong> ${getTierBadge(u)}</div>
        <div><strong>Діє до:</strong> ${u.sub_expires ? new Date(u.sub_expires).toLocaleString('uk-UA') : '—'}</div>
        <div><strong>Пресети:</strong> ${u.presets_count ?? 0}</div>
        <div><strong>Створено:</strong> ${u.created_at ? new Date(u.created_at).toLocaleString('uk-UA') : '—'}</div>
        <div><strong>Оновлено:</strong> ${u.updated_at ? new Date(u.updated_at).toLocaleString('uk-UA') : '—'}</div>
      </div>
      ${u.presets && u.presets.length ? `
      <h4 style="margin-top:18px;margin-bottom:8px">Пресети</h4>
      <table style="min-width:auto"><thead><tr><th>Назва</th><th>Формат</th><th>Варіанти</th><th>Стиль</th><th>Активний</th></tr></thead><tbody>
        ${u.presets.map(p => `<tr>
          <td>${esc(p.name)}</td>
          <td>${esc(p.aspect_ratio||'—')}</td>
          <td>${p.num_variants??'—'}</td>
          <td style="max-width:200px;overflow:hidden;text-overflow:ellipsis">${esc(p.style_suffix||'—')}</td>
          <td>${p.is_active ? '✅' : '—'}</td>
        </tr>`).join('')}
      </tbody></table>` : ''}
    `;
  } catch(e) {
    document.getElementById('modalBody').innerHTML = '<p style="color:var(--danger)">Помилка завантаження</p>';
  }
}

function closeUserModal() { document.getElementById('userModal').classList.remove('active'); }

/* ──────────────────────────────────────────────────────────
   EDIT USER MODAL
   ────────────────────────────────────────────────────────── */
async function openEditUser(id) {
  document.getElementById('editModalBody').innerHTML = '<div class="loading"><div class="spinner"></div></div>';
  document.getElementById('editUserModal').classList.add('active');
  try {
    const r = await fetch('/admin/api/users/' + id);
    if (!r.ok) throw new Error();
    const u = await r.json();
    document.getElementById('editModalBody').innerHTML = `
      <form onsubmit="saveUser(event, ${u.id})">
        <div class="form-group">
          <label>Статус підписки</label>
          <select name="subscription_tier">
            <option value="free" ${u.subscription_tier==='free'?'selected':''}>Free (10 генерацій/день)</option>
            <option value="premium" ${u.subscription_tier==='premium'?'selected':''}>Premium ($10)</option>
            <option value="pro" ${u.subscription_tier==='pro'?'selected':''}>Pro ($15)</option>
            <option value="frozen" ${u.subscription_tier==='frozen'?'selected':''}>Frozen (заблокований)</option>
          </select>
        </div>
        <div class="form-actions">
          <button type="submit" class="btn btn-primary">💾 Зберегти</button>
          <button type="button" class="btn btn-secondary" onclick="closeEditModal()">Скасувати</button>
        </div>
      </form>
    `;
  } catch(e) {
    document.getElementById('editModalBody').innerHTML = '<p style="color:var(--danger)">Помилка</p>';
  }
}

async function saveUser(evt, id) {
  evt.preventDefault();
  const form = evt.target;
  const data = {
    subscription_tier: form.subscription_tier.value
  };
  try {
    const r = await fetch('/admin/api/users/' + id, {
      method:'PUT',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify(data)
    });
    if (!r.ok) throw new Error();
    showToast('Збережено!');
    closeEditModal();
    loadUsers();
  } catch(e) {
    showToast('Помилка збереження', 'error');
  }
}

function closeEditModal() { document.getElementById('editUserModal').classList.remove('active'); }

/* ──────────────────────────────────────────────────────────
   CSV EXPORT
   ────────────────────────────────────────────────────────── */
function exportUsersCSV() {
  if (!filteredUsers.length) { showToast('Немає даних для експорту','error'); return; }
  const headers = ['ID','Telegram ID','Username','Tier','Expires','Created'];
  const rows = filteredUsers.map(u => [
    u.id, u.telegram_id, u.username||'', u.subscription_tier||'free',
    u.sub_expires||'', u.created_at||''
  ]);
  let csv = headers.join(',') + '\n' + rows.map(r => r.map(v => `"${String(v).replace(/"/g,'""')}"`).join(',')).join('\n');
  const blob = new Blob(['\uFEFF'+csv], {type:'text/csv;charset=utf-8;'});
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = 'imagio_users_' + new Date().toISOString().slice(0,10) + '.csv';
  a.click(); URL.revokeObjectURL(url);
}

/* ──────────────────────────────────────────────────────────
   USER PRESETS MODAL
   ────────────────────────────────────────────────────────── */
async function showUserPresets(id) {
  document.getElementById('modalBody').innerHTML = '<div class="loading"><div class="spinner"></div></div>';
  document.getElementById('userModal').classList.add('active');
  try {
    const r = await fetch('/admin/api/users/' + id);
    if (!r.ok) throw new Error();
    const u = await r.json();
    document.getElementById('modalTitle').textContent = (u.username ? '@' + u.username : 'User #' + u.telegram_id) + ' — пресети';
    if (!u.presets || !u.presets.length) {
      document.getElementById('modalBody').innerHTML = '<p style="color:var(--muted);text-align:center;padding:20px">У цього користувача немає пресетів</p>';
      return;
    }
    document.getElementById('modalBody').innerHTML = `
      <table style="min-width:auto"><thead><tr><th>Назва</th><th>Формат</th><th>Варіанти</th><th>Стиль</th><th>Активний</th></tr></thead><tbody>
        ${u.presets.map(p => `<tr>
          <td>${esc(p.name)}</td>
          <td>${esc(p.aspect_ratio||'—')}</td>
          <td>${p.num_variants??'—'}</td>
          <td style="max-width:200px;overflow:hidden;text-overflow:ellipsis">${esc(p.style_suffix||'—')}</td>
          <td>${p.is_active ? '✅' : '—'}</td>
        </tr>`).join('')}
      </tbody></table>
    `;
  } catch(e) {
    document.getElementById('modalBody').innerHTML = '<p style="color:var(--danger)">Помилка завантаження</p>';
  }
}

/* ──────────────────────────────────────────────────────────
   PAYMENTS — LOAD
   ────────────────────────────────────────────────────────── */
async function loadPayments() {
  const search = document.getElementById('paymentSearch').value.trim();
  const status = document.getElementById('paymentStatusFilter').value;
  const params = new URLSearchParams();
  if (search) params.set('search', search);
  if (status) params.set('status', status);

  document.getElementById('paymentsTableBody').innerHTML = '<tr><td colspan="7" class="loading"><div class="spinner"></div>Завантаження…</td></tr>';

  try {
    const r = await fetch('/admin/api/payments?' + params);
    if (!r.ok) throw new Error('payments fetch failed');
    const payments = await r.json();

    if (!payments.length) {
      document.getElementById('paymentsTableBody').innerHTML = '<tr><td colspan="7" style="text-align:center;padding:24px;color:var(--muted)">Платежів не знайдено</td></tr>';
      return;
    }

    document.getElementById('paymentsTableBody').innerHTML = payments.map(p => {
      const statusMap = {pending:'badge-pending',approved:'badge-active',declined:'badge-expired',refunded:'badge-inactive'};
      const statusCls = statusMap[p.status] || 'badge-inactive';
      const created = p.created_at ? new Date(p.created_at).toLocaleString('uk-UA') : '—';
      const userLabel = p.username ? '@' + esc(p.username) : (p.telegram_id || '—');
      return `<tr>
        <td style="font-family:monospace;font-size:12px">${esc(p.order_reference)}</td>
        <td>${userLabel}</td>
        <td><b>$${p.amount}</b> ${esc(p.currency)}</td>
        <td>${esc(p.plan_id || '—')}</td>
        <td><span class="badge ${statusCls}">${p.status}</span></td>
        <td>${esc(p.card_pan || '—')} ${esc(p.card_type || '')}</td>
        <td>${created}</td>
      </tr>`;
    }).join('');
  } catch(e) {
    console.error('Payments error:', e);
    document.getElementById('paymentsTableBody').innerHTML = '<tr><td colspan="7" style="color:var(--danger);text-align:center;padding:20px">Помилка завантаження</td></tr>';
  }
}

/* ──────────────────────────────────────────────────────────
   PLANS — LOAD
   ────────────────────────────────────────────────────────── */
async function loadPlans() {
  document.getElementById('plansTableBody').innerHTML = '<tr><td colspan="7" class="loading"><div class="spinner"></div></td></tr>';
  try {
    const r = await fetch('/admin/api/plans');
    if (!r.ok) throw new Error('plans fetch failed');
    const plans = await r.json();

    document.getElementById('plansTableBody').innerHTML = plans.map(p => {
      const activeBadge = p.is_active ? '<span class="badge badge-active">Активний</span>' : '<span class="badge badge-inactive">Вимкнено</span>';
      return `<tr>
        <td style="font-family:monospace">${esc(p.id)}</td>
        <td><b>${esc(p.name)}</b></td>
        <td>$${p.price}</td>
        <td><span class="badge badge-premium">${esc(p.tier)}</span></td>
        <td>${p.period_days} днів</td>
        <td>${activeBadge}</td>
        <td>
          <button class="btn btn-secondary" style="padding:5px 10px;font-size:12px" onclick="togglePlan('${esc(p.id)}', ${!p.is_active})">${p.is_active ? '⏸ Вимкнути' : '▶ Увімкнути'}</button>
        </td>
      </tr>`;
    }).join('');
  } catch(e) {
    console.error('Plans error:', e);
    document.getElementById('plansTableBody').innerHTML = '<tr><td colspan="7" style="color:var(--danger);text-align:center">Помилка</td></tr>';
  }
}

async function togglePlan(planId, newActive) {
  try {
    const r = await fetch('/admin/api/plans/' + planId, {
      method: 'PUT',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({is_active: newActive})
    });
    if (!r.ok) throw new Error();
    showToast(newActive ? 'План увімкнено' : 'План вимкнено');
    loadPlans();
  } catch(e) {
    showToast('Помилка оновлення плану', 'error');
  }
}

/* ──────────────────────────────────────────────────────────
   INIT
   ────────────────────────────────────────────────────────── */
document.addEventListener('DOMContentLoaded', () => {
  loadStats();
  loadUsers();
});
</script>
</body>
</html>"""
