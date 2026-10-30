// Mobile nav toggle
document.getElementById('navToggle').addEventListener('click', () => {
    document.querySelector('.nav-links').classList.toggle('open');
});

// Demo tabs
document.querySelectorAll('.demo-tab').forEach(tab => {
    tab.addEventListener('click', () => {
        document.querySelectorAll('.demo-tab').forEach(t => t.classList.remove('active'));
        document.querySelectorAll('.demo-panel').forEach(p => p.classList.remove('active'));
        tab.classList.add('active');
        document.getElementById(`demo-${tab.dataset.demo}`).classList.add('active');
    });
});

// Smooth scroll for nav links
document.querySelectorAll('a[href^="#"]').forEach(a => {
    a.addEventListener('click', e => {
        e.preventDefault();
        const target = document.querySelector(a.getAttribute('href'));
        if (target) {
            target.scrollIntoView({ behavior: 'smooth', block: 'start' });
            document.querySelector('.nav-links').classList.remove('open');
        }
    });
});
