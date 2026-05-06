(function () {
  function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text || '';
    return div.innerHTML;
  }

  function sanitizeUrl(rawUrl) {
    try {
      const url = String(rawUrl || '').trim();
      if (!url) return '';
      const parsed = new URL(url, window.location.origin);
      if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
        return '';
      }
      return parsed.href;
    } catch (error) {
      return '';
    }
  }

  function trimTrailingPunctuation(url) {
    return String(url || '').replace(/[),.;:!?]+$/, '');
  }

  function formatInline(text) {
    const source = String(text || '');
    const pattern = /\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)|(https?:\/\/[^\s<]+)/g;
    let html = '';
    let lastIndex = 0;
    let match;

    while ((match = pattern.exec(source)) !== null) {
      html += escapeHtml(source.slice(lastIndex, match.index));

      const label = match[1] || '';
      const rawUrl = match[2] || trimTrailingPunctuation(match[3] || '');
      const safeUrl = sanitizeUrl(rawUrl);
      if (safeUrl) {
        const linkText = label || rawUrl;
        html += `<a href="${escapeHtml(safeUrl)}" target="_blank" rel="noopener noreferrer">${escapeHtml(linkText)}</a>`;
      } else {
        html += escapeHtml(match[0]);
      }

      lastIndex = match.index + match[0].length;
    }

    html += escapeHtml(source.slice(lastIndex));
    return html;
  }

  function formatMessage(text) {
    const source = String(text || '').replace(/\r\n/g, '\n').trim();
    if (!source) {
      return '';
    }

    const lines = source.split('\n').map((line) => line.trim()).filter((line, index, arr) => {
      return !(line === '' && arr[index - 1] === '');
    });

    let html = '';
    let listOpen = false;

    for (const line of lines) {
      const bulletMatch = /^[-*•]\s+(.+)$/.exec(line);
      if (bulletMatch) {
        if (!listOpen) {
          html += '<ul>';
          listOpen = true;
        }
        html += '<li>' + formatInline(bulletMatch[1]) + '</li>';
        continue;
      }

      if (listOpen) {
        html += '</ul>';
        listOpen = false;
      }

      html += '<p>' + formatInline(line) + '</p>';
    }

    if (listOpen) {
      html += '</ul>';
    }

    return html;
  }

  function initAssistant(root) {
    const endpoint = root.dataset.chatEndpoint || '/ai/chat';
    const newsEndpoint = root.dataset.newsEndpoint || '/ai/news';
    const welcomeText = root.dataset.welcome || '';

    const messagesEl = root.querySelector('[data-chat-messages]');
    const typingEl = root.querySelector('[data-chat-typing]');
    const inputEl = root.querySelector('[data-chat-input]');
    const sendBtn = root.querySelector('[data-chat-send]');
    const clearBtn = root.querySelector('[data-chat-clear]');
    const newsContainer = root.querySelector('[data-news-container]');
    const newsButton = root.querySelector('[data-news-refresh]');

    root.querySelectorAll('[data-collapse-trigger]').forEach((button) => {
      button.addEventListener('click', function () {
        const panelId = this.getAttribute('aria-controls');
        if (!panelId) return;
        const panel = root.querySelector(`#${panelId}`);
        if (!panel) return;
        const expanded = this.getAttribute('aria-expanded') === 'true';
        this.setAttribute('aria-expanded', expanded ? 'false' : 'true');
        panel.hidden = expanded;
      });
    });

    function scrollToBottom() {
      if (messagesEl) {
        messagesEl.scrollTop = messagesEl.scrollHeight;
      }
    }

    function addMessage(text, isUser) {
      if (!messagesEl) return;
      const item = document.createElement('div');
      item.className = 'assistant-message ' + (isUser ? 'user' : 'bot');
      const icon = isUser ? 'fa-user' : 'fa-robot';
      item.innerHTML = `
        <div class="assistant-avatar"><i class="fa-solid ${icon}"></i></div>
        <div class="assistant-bubble">${isUser ? escapeHtml(text) : formatMessage(text)}</div>
      `;
      messagesEl.appendChild(item);
      scrollToBottom();
    }

    function showTyping() {
      if (typingEl) {
        typingEl.style.display = 'block';
        scrollToBottom();
      }
    }

    function hideTyping() {
      if (typingEl) {
        typingEl.style.display = 'none';
      }
    }

    function setLoading(loading) {
      if (sendBtn) sendBtn.disabled = loading;
      if (inputEl) inputEl.disabled = loading;
    }

    function autoResize() {
      if (!inputEl) return;
      inputEl.style.height = 'auto';
      inputEl.style.height = Math.min(inputEl.scrollHeight, 150) + 'px';
    }

    async function sendMessage(prefill) {
      if (!inputEl) return;
      const text = typeof prefill === 'string' ? prefill.trim() : inputEl.value.trim();
      if (!text) return;

      if (typeof prefill !== 'string') {
        inputEl.value = '';
        autoResize();
      } else {
        inputEl.value = '';
        autoResize();
      }

      addMessage(text, true);
      setLoading(true);
      showTyping();

      try {
        const response = await fetch(endpoint, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ message: text })
        });
        const data = await response.json();
        hideTyping();

        if (data.success) {
          addMessage(data.answer, false);
        } else {
          let reply = data.answer || 'Chưa có kết quả phù hợp.';
          if (data.suggestions && data.suggestions.length) {
            reply += '\n\n- Chủ đề liên quan: ' + data.suggestions.join(', ');
          }
          addMessage(reply, false);
        }
      } catch (error) {
        hideTyping();
        addMessage('Lỗi kết nối dịch vụ. Thử lại sau.', false);
      }

      setLoading(false);
      inputEl.focus();
    }

    async function refreshNews() {
      if (!newsContainer || !newsButton) return;
      newsButton.disabled = true;
      newsButton.innerHTML = '<i class="fa-solid fa-spinner fa-spin me-2"></i>Đang tải';
      try {
        const response = await fetch(newsEndpoint + '?limit=10');
        const data = await response.json();
        if (data.success && Array.isArray(data.articles)) {
          newsContainer.innerHTML = data.articles.map((article) => `
            <a href="${article.link}" target="_blank" class="assistant-news-item">
              <div class="assistant-news-title">${escapeHtml(article.title)}</div>
              <div class="assistant-news-meta">
                <i class="fa-solid fa-globe me-1"></i>${escapeHtml(article.source || '')}
                ${article.date ? `<span class="ms-2"><i class="fa-regular fa-calendar me-1"></i>${escapeHtml(article.date)}</span>` : ''}
              </div>
            </a>
          `).join('');
        }
      } catch (error) {
        // Keep current news list when refresh fails.
      }
      newsButton.disabled = false;
      newsButton.innerHTML = '<i class="fa-solid fa-rotate me-2"></i>Tải lại nguồn tin';
    }

    root.querySelectorAll('[data-ask-question]').forEach((button) => {
      button.addEventListener('click', function () {
        sendMessage(this.dataset.askQuestion || '');
      });
    });

    if (clearBtn && messagesEl) {
      clearBtn.addEventListener('click', function () {
        messagesEl.innerHTML = '';
        addMessage(welcomeText, false);
      });
    }

    if (newsButton) {
      newsButton.addEventListener('click', refreshNews);
    }

    if (sendBtn) {
      sendBtn.addEventListener('click', function () {
        sendMessage();
      });
    }

    if (inputEl) {
      inputEl.addEventListener('input', autoResize);
      inputEl.addEventListener('keydown', function (event) {
        if (event.key === 'Enter' && !event.shiftKey) {
          event.preventDefault();
          sendMessage();
        }
      });
      autoResize();
    }

    if (messagesEl && !messagesEl.children.length) {
      addMessage(welcomeText, false);
    }
  }

  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('[data-ai-assistant]').forEach(initAssistant);
  });
})();
