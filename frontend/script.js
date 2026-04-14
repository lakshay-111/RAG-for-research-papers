// Scroll Animations Observer
document.addEventListener('DOMContentLoaded', () => {
    const observer = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                entry.target.classList.add('visible');
            }
        });
    }, { threshold: 0.1 });

    document.querySelectorAll('.scroll-animate').forEach((el) => {
        observer.observe(el);
    });

    loadCollections();
});

// Tab Switching
function switchTab(tabId) {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(c => c.classList.add('hidden'));
    
    event.target.classList.add('active');
    document.getElementById(`${tabId}-tab`).classList.remove('hidden');
    document.getElementById(`${tabId}-tab`).classList.add('active');
}

// Drag and drop utilities
const dropArea = document.getElementById('file-drop-area');
const fileInput = document.getElementById('local-files');
const fileList = document.getElementById('file-list');

['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
    dropArea.addEventListener(eventName, preventDefaults, false);
});
function preventDefaults(e) { e.preventDefault(); e.stopPropagation(); }

['dragenter', 'dragover'].forEach(eventName => {
    dropArea.addEventListener(eventName, () => dropArea.classList.add('dragover'), false);
});
['dragleave', 'drop'].forEach(eventName => {
    dropArea.addEventListener(eventName, () => dropArea.classList.remove('dragover'), false);
});

dropArea.addEventListener('drop', handleDrop, false);
fileInput.addEventListener('change', handleFiles, false);

function handleDrop(e) {
    let dt = e.dataTransfer;
    let files = dt.files;
    fileInput.files = files; // Assign to input
    handleFiles();
}

function handleFiles() {
    fileList.innerHTML = '';
    const files = [...fileInput.files];
    if(files.length > 0) {
        files.forEach(file => {
            const el = document.createElement('div');
            el.textContent = `📄 ${file.name}`;
            fileList.appendChild(el);
        });
    }
}

// Set status message
function setStatus(msg, isError=false) {
    const statusEl = document.getElementById('action-status');
    statusEl.textContent = msg;
    statusEl.style.color = isError ? '#D32F2F' : 'inherit';
}

// Load Collections
async function loadCollections() {
    const select = document.getElementById('collection-select');
    try {
        const res = await fetch('/api/collections');
        const data = await res.json();
        
        select.innerHTML = '';
        if (data.collections.length === 0) {
            select.innerHTML = '<option value="">No collections found</option>';
        } else {
            data.collections.forEach(c => {
                const opt = document.createElement('option');
                opt.value = c;
                opt.textContent = c;
                select.appendChild(opt);
            });
        }
    } catch (e) {
        select.innerHTML = '<option value="">Failed to load</option>';
    }
}

document.getElementById('refresh-collections').addEventListener('click', loadCollections);

// Handle ArXiv Search
document.getElementById('arxiv-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const query = document.getElementById('arxiv-query').value;
    const mode = document.getElementById('arxiv-mode').value;
    const num = document.getElementById('arxiv-num').value;
    const btn = e.target.querySelector('button');

    btn.disabled = true;
    setStatus('Searching ArXiv and downloading papers. Please wait...');
    
    try {
        const res = await fetch('/api/arxiv/search', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ query, search_mode: mode, n_results: parseInt(num) })
        });
        const data = await res.json();
        
        if (res.ok && data.status === 'success') {
            setStatus(`Success! Papers ingested to collection: ${data.collection_name}`);
            await loadCollections();
            document.getElementById('collection-select').value = data.collection_name;
        } else {
            setStatus(data.message || 'Error occurred', true);
        }
    } catch (err) {
        setStatus('Network error occurred.', true);
    } finally {
        btn.disabled = false;
    }
});

// Handle Local Upload
document.getElementById('upload-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    if (fileInput.files.length === 0) {
        setStatus('Please select files first.', true);
        return;
    }

    const btn = e.target.querySelector('button');
    btn.disabled = true;
    setStatus('Uploading and extracting text. Please wait...');

    const formData = new FormData();
    for (const file of fileInput.files) {
        formData.append('files', file);
    }

    try {
        const res = await fetch('/api/local/upload', {
            method: 'POST',
            body: formData
        });
        const data = await res.json();
        
        if (res.ok && data.status === 'success') {
            setStatus(`Success! Mined ${data.files.length} files to ${data.collection_name}`);
            await loadCollections();
            document.getElementById('collection-select').value = data.collection_name;
            fileInput.value = '';
            fileList.innerHTML = '';
        } else {
            setStatus(data.message || 'Error occurred', true);
        }
    } catch (err) {
        setStatus('Network error occurred.', true);
    } finally {
        btn.disabled = false;
    }
});

// Handle Chat
const chatForm = document.getElementById('chat-form');
const chatBox = document.getElementById('chat-box');
const chatInput = document.getElementById('chat-input');
const chatChunks = document.getElementById('chat-chunks');

function appendMessage(role, text) {
    const msgDiv = document.createElement('div');
    msgDiv.className = `message ${role} glass`;
    
    if (role === 'assistant') {
        msgDiv.innerHTML = marked.parse(text);
    } else {
        msgDiv.textContent = text;
    }
    
    chatBox.appendChild(msgDiv);
    chatBox.scrollTop = chatBox.scrollHeight;
    return msgDiv;
}

chatForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    
    const query = chatInput.value.trim();
    if (!query) return;
    
    const collectionName = document.getElementById('collection-select').value;
    if (!collectionName) {
        appendMessage('system', 'Please select a collection first.');
        return;
    }
    
    // UI Updates
    appendMessage('user', query);
    chatInput.value = '';
    const btn = chatForm.querySelector('button');
    btn.disabled = true;
    
    // Create assistant message placeholder
    const msgDiv = document.createElement('div');
    msgDiv.className = 'message assistant glass loading-dots';
    msgDiv.textContent = 'Thinking';
    chatBox.appendChild(msgDiv);
    chatBox.scrollTop = chatBox.scrollHeight;

    try {
        const response = await fetch('/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                query: query,
                collection_name: collectionName,
                n_chunks: parseInt(chatChunks.value) || 3
            })
        });

        if (!response.ok) {
            throw new Error(`Server returned ${response.status}`);
        }

        msgDiv.classList.remove('loading-dots');
        msgDiv.textContent = ''; // Clear 'Thinking'
        
        // Read stream
        const reader = response.body.getReader();
        const decoder = new TextDecoder("utf-8");
        let done = false;
        let fullText = '';

        while (!done) {
            const { value, done: readerDone } = await reader.read();
            done = readerDone;
            if (value) {
                const chunk = decoder.decode(value, { stream: true });
                fullText += chunk;
                msgDiv.innerHTML = marked.parse(fullText);
                chatBox.scrollTop = chatBox.scrollHeight;
            }
        }
    } catch (err) {
        msgDiv.classList.remove('loading-dots');
        msgDiv.textContent = 'Sorry, an error occurred while generating the response.';
    } finally {
        btn.disabled = false;
        chatInput.focus();
    }
});
