// Dashboard Charts and Visualizations
// Sử dụng Chart.js để tạo biểu đồ đẹp

document.addEventListener('DOMContentLoaded', function() {
    // Kiểm tra xem Chart.js đã được load chưa
    if (typeof Chart === 'undefined') {
        console.warn('Chart.js chưa được load. Vui lòng thêm Chart.js vào template.');
        return;
    }

    // Cấu hình chung cho tất cả charts
    Chart.defaults.font.family = "'Be Vietnam Pro', sans-serif";
    Chart.defaults.font.size = 12;
    Chart.defaults.color = '#64748b';

    // 1. Biểu đồ tiến độ công việc (Doughnut Chart)
    const taskProgressCanvas = document.getElementById('taskProgressChart');
    if (taskProgressCanvas) {
        const ctx = taskProgressCanvas.getContext('2d');
        
        // Gradient colors
        const completedGradient = ctx.createLinearGradient(0, 0, 0, 400);
        completedGradient.addColorStop(0, '#10b981');
        completedGradient.addColorStop(1, '#059669');
        
        const doingGradient = ctx.createLinearGradient(0, 0, 0, 400);
        doingGradient.addColorStop(0, '#3b82f6');
        doingGradient.addColorStop(1, '#1d4ed8');
        
        const pendingGradient = ctx.createLinearGradient(0, 0, 0, 400);
        pendingGradient.addColorStop(0, '#f59e0b');
        pendingGradient.addColorStop(1, '#d97706');

        new Chart(ctx, {
            type: 'doughnut',
            data: {
                labels: ['Hoàn thành', 'Đang làm', 'Chưa tiếp nhận'],
                datasets: [{
                    data: [
                        parseInt(taskProgressCanvas.dataset.completed || 0),
                        parseInt(taskProgressCanvas.dataset.doing || 0),
                        parseInt(taskProgressCanvas.dataset.pending || 0)
                    ],
                    backgroundColor: [completedGradient, doingGradient, pendingGradient],
                    borderWidth: 0,
                    hoverOffset: 10
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        position: 'bottom',
                        labels: {
                            padding: 15,
                            usePointStyle: true,
                            pointStyle: 'circle',
                            font: {
                                size: 13,
                                weight: '600'
                            }
                        }
                    },
                    tooltip: {
                        backgroundColor: 'rgba(15, 23, 42, 0.95)',
                        padding: 12,
                        cornerRadius: 8,
                        titleFont: {
                            size: 14,
                            weight: 'bold'
                        },
                        bodyFont: {
                            size: 13
                        },
                        callbacks: {
                            label: function(context) {
                                const total = context.dataset.data.reduce((a, b) => a + b, 0);
                                const percentage = ((context.parsed / total) * 100).toFixed(1);
                                return ` ${context.label}: ${context.parsed} (${percentage}%)`;
                            }
                        }
                    }
                },
                cutout: '70%',
                animation: {
                    animateRotate: true,
                    animateScale: true,
                    duration: 1000,
                    easing: 'easeInOutQuart'
                }
            }
        });
    }

    // 2. Biểu đồ xu hướng công việc theo thời gian (Line Chart)
    const taskTrendCanvas = document.getElementById('taskTrendChart');
    if (taskTrendCanvas) {
        const ctx = taskTrendCanvas.getContext('2d');
        
        const gradient = ctx.createLinearGradient(0, 0, 0, 300);
        gradient.addColorStop(0, 'rgba(0, 102, 255, 0.3)');
        gradient.addColorStop(1, 'rgba(0, 102, 255, 0.01)');

        new Chart(ctx, {
            type: 'line',
            data: {
                labels: ['T2', 'T3', 'T4', 'T5', 'T6', 'T7', 'CN'],
                datasets: [{
                    label: 'Công việc hoàn thành',
                    data: JSON.parse(taskTrendCanvas.dataset.weeklyData || '[0,0,0,0,0,0,0]'),
                    borderColor: '#0066FF',
                    backgroundColor: gradient,
                    borderWidth: 3,
                    fill: true,
                    tension: 0.4,
                    pointRadius: 5,
                    pointHoverRadius: 7,
                    pointBackgroundColor: '#fff',
                    pointBorderColor: '#0066FF',
                    pointBorderWidth: 2,
                    pointHoverBackgroundColor: '#0066FF',
                    pointHoverBorderColor: '#fff',
                    pointHoverBorderWidth: 3
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        display: false
                    },
                    tooltip: {
                        backgroundColor: 'rgba(15, 23, 42, 0.95)',
                        padding: 12,
                        cornerRadius: 8,
                        titleFont: {
                            size: 14,
                            weight: 'bold'
                        },
                        bodyFont: {
                            size: 13
                        }
                    }
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        grid: {
                            color: 'rgba(148, 163, 184, 0.1)',
                            drawBorder: false
                        },
                        ticks: {
                            stepSize: 1,
                            font: {
                                size: 11
                            }
                        }
                    },
                    x: {
                        grid: {
                            display: false,
                            drawBorder: false
                        },
                        ticks: {
                            font: {
                                size: 11,
                                weight: '600'
                            }
                        }
                    }
                },
                animation: {
                    duration: 1500,
                    easing: 'easeInOutQuart'
                }
            }
        });
    }

    // 3. Biểu đồ phân bố công việc theo đơn vị (Bar Chart)
    const unitDistributionCanvas = document.getElementById('unitDistributionChart');
    if (unitDistributionCanvas) {
        const ctx = unitDistributionCanvas.getContext('2d');
        
        new Chart(ctx, {
            type: 'bar',
            data: {
                labels: JSON.parse(unitDistributionCanvas.dataset.units || '[]'),
                datasets: [{
                    label: 'Số công việc',
                    data: JSON.parse(unitDistributionCanvas.dataset.counts || '[]'),
                    backgroundColor: [
                        'rgba(0, 102, 255, 0.8)',
                        'rgba(16, 185, 129, 0.8)',
                        'rgba(245, 158, 11, 0.8)',
                        'rgba(139, 92, 246, 0.8)',
                        'rgba(236, 72, 153, 0.8)'
                    ],
                    borderRadius: 8,
                    borderSkipped: false
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        display: false
                    },
                    tooltip: {
                        backgroundColor: 'rgba(15, 23, 42, 0.95)',
                        padding: 12,
                        cornerRadius: 8,
                        titleFont: {
                            size: 14,
                            weight: 'bold'
                        },
                        bodyFont: {
                            size: 13
                        }
                    }
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        grid: {
                            color: 'rgba(148, 163, 184, 0.1)',
                            drawBorder: false
                        },
                        ticks: {
                            stepSize: 1,
                            font: {
                                size: 11
                            }
                        }
                    },
                    x: {
                        grid: {
                            display: false,
                            drawBorder: false
                        },
                        ticks: {
                            font: {
                                size: 11,
                                weight: '600'
                            }
                        }
                    }
                },
                animation: {
                    duration: 1200,
                    easing: 'easeInOutQuart'
                }
            }
        });
    }

    // Animate numbers on scroll
    const animateValue = (element, start, end, duration) => {
        let startTimestamp = null;
        const step = (timestamp) => {
            if (!startTimestamp) startTimestamp = timestamp;
            const progress = Math.min((timestamp - startTimestamp) / duration, 1);
            element.textContent = Math.floor(progress * (end - start) + start);
            if (progress < 1) {
                window.requestAnimationFrame(step);
            }
        };
        window.requestAnimationFrame(step);
    };

    // Animate stat numbers when they come into view
    const statNumbers = document.querySelectorAll('.stat-number');
    const observer = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting && !entry.target.classList.contains('animated')) {
                const finalValue = parseInt(entry.target.textContent);
                entry.target.textContent = '0';
                animateValue(entry.target, 0, finalValue, 1000);
                entry.target.classList.add('animated');
            }
        });
    }, { threshold: 0.5 });

    statNumbers.forEach(num => observer.observe(num));
});
