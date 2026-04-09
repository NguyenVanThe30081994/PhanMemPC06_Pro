document.addEventListener("DOMContentLoaded", () => {
    // Kích hoạt Sidebar Tooltips nếu có (Mở rộng cho tính năng tương lai)
    
    // Tự động Highlight Sidebar Menu dựa trên URL hiện tại
    const path = window.location.pathname;
    document.querySelectorAll('.sidebar .nav-link').forEach(link => {
        link.classList.remove('active');
        if (link.getAttribute('href') === path) {
            link.classList.add('active');
        } else if (path.startsWith('/config') && link.getAttribute('href') === '/config') {
             link.classList.add('active');
        } else if (path.startsWith('/chat') && link.getAttribute('href') === '/chat') {
             link.classList.add('active');
        }
    });

    // Auto-Dismiss Flash messages
    setTimeout(() => {
        document.querySelectorAll('.alert-auto').forEach(alert => {
            alert.style.transition = "opacity 0.6s ease";
            alert.style.opacity = 0;
            setTimeout(() => alert.remove(), 600);
        });
    }, 4000);

    // Sidebar Mobile Toggle
    const toggleBtn = document.getElementById('mobileToggleBtn');
    const sidebar = document.getElementById('sidebar');
    const overlay = document.getElementById('sidebarOverlay');

    if(toggleBtn && sidebar && overlay) {
        toggleBtn.addEventListener('click', () => {
            sidebar.classList.toggle('active');
            overlay.classList.toggle('active');
        });

        overlay.addEventListener('click', () => {
            sidebar.classList.remove('active');
            overlay.classList.remove('active');
        });
    }
});

// Update File Name utility
function updateFileName(input) {
    const container = input.closest('.file-up') || input.closest('label') || input.parentElement;
    const nameDisplay = container.querySelector('.file-name') || container.querySelector('#fileNameDisplay');
    
    if (nameDisplay) {
        if (input.files && input.files.length > 0) {
            const fileName = input.files[0].name;
            nameDisplay.innerHTML = `<i class="fa-solid fa-check-circle me-1"></i> Đã chọn: <strong>${fileName}</strong>`;
            nameDisplay.classList.remove('d-none');
            nameDisplay.style.display = 'block';
            // Visual feedback on the container
            container.style.borderColor = 'var(--success)';
            container.style.backgroundColor = 'rgba(5, 150, 105, 0.05)';
        } else {
            nameDisplay.innerHTML = '';
            nameDisplay.classList.add('d-none');
            container.style.borderColor = '';
            container.style.backgroundColor = '';
        }
    }
}
