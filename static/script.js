// API Configuration
const API_BASE = 'http://localhost:5000';

// DOM Elements
const searchQueryInput = document.getElementById('search-query');
const searchModeSelect = document.getElementById('search-mode');
const numPapersInput = document.getElementById('num-papers');
const searchBtn = document.getElementById('search-btn');
const statusSearch = document.getElementById('status-search');
const collectionInfo = document.getElementById('collection-info');

const questionQueryInput = document.getElementById('question-query');
const numChunksInput = document.getElementById('num-chunks');
const askBtn = document.getElementById('ask-btn');
const statusQuestion = document.getElementById('status-question');

const answerBox = document.getElementById('answer-box');
const sourcesList = document.getElementById('sources-list');
const responseSection = document.getElementById('response-section');
const newSearchBtn = document.getElementById('new-search-btn');

// State
let currentCollection = null;

// Event Listeners
searchBtn.addEventListener('click', handleSearch);
askBtn.addEventListener('click', handleAsk);
newSearchBtn.addEventListener('click', resetUI);

// Enter key shortcuts
searchQueryInput.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') handleSearch();
});

questionQueryInput.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') handleAsk();
});

// Search Handler
async function handleSearch() {
    const query = searchQueryInput.value.trim();
    const mode = searchModeSelect.value;
    const numPapers = parseInt(numPapersInput.value) || 3;

    if (!query) {
        showStatus(statusSearch, 'Please enter a search query', 'error');
        return;
    }

    try {
        showStatus(statusSearch, 'Searching arXiv and indexing papers...', 'loading');
        searchBtn.disabled = true;
        askBtn.disabled = true;

        const response = await fetch(`${API_BASE}/api/search-arxiv`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                query: query,
                search_mode: mode,
                num_papers: numPapers
            })
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.error || `Server error: ${response.status}`);
        }

        const data = await response.json();
        currentCollection = data.collection_name;

        showStatus(statusSearch, `✓ Successfully indexed ${numPapers} papers. Ready to ask questions!`, 'success');
        showCollectionInfo(numPapers);
        
        questionQueryInput.focus();
        askBtn.disabled = false;
    } catch (error) {
        showStatus(statusSearch, `Error: ${error.message}`, 'error');
        askBtn.disabled = true;
    } finally {
        searchBtn.disabled = false;
    }
}

// Ask Handler
async function handleAsk() {
    const query = questionQueryInput.value.trim();
    const k = parseInt(numChunksInput.value) || 5;

    if (!query) {
        showStatus(statusQuestion, 'Please enter a question', 'error');
        return;
    }

    if (!currentCollection) {
        showStatus(statusQuestion, 'Please search for papers first', 'error');
        return;
    }

    try {
        showStatus(statusQuestion, 'Thinking...', 'loading');
        askBtn.disabled = true;

        const response = await fetch(`${API_BASE}/api/ask`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                query: query,
                k: k
            })
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.error || `Server error: ${response.status}`);
        }

        const data = await response.json();
        
        displayAnswer(data.answer);
        displaySources(data.sources);
        showStatus(statusQuestion, `✓ Found ${data.num_sources} relevant sources`, 'success');
        responseSection.classList.remove('hidden');

    } catch (error) {
        showStatus(statusQuestion, `Error: ${error.message}`, 'error');
    } finally {
        askBtn.disabled = false;
    }
}

// Display Answer
function displayAnswer(answer) {
    // Format markdown and special patterns
    let formatted = answer
        // Bold text
        .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
        // Bullet points
        .replace(/^\s*•\s+(.+)$/gm, '<div style="margin-left: 1.5rem; color: #FFD700;">• $1</div>')
        // Section headers (numbered or text)
        .replace(/^(#{1,6})\s+(.+)$/gm, '<div style="font-weight: 600; margin-top: 1rem; color: #fff;">$2</div>')
        // Line breaks
        .replace(/\n/g, '<br>');

    answerBox.innerHTML = formatted;
}

// Display Sources
function displaySources(sources) {
    sourcesList.innerHTML = '';
    
    if (!sources || sources.length === 0) {
        sourcesList.innerHTML = '<div class="source-item">No sources found</div>';
        return;
    }

    sources.forEach((source, index) => {
        const sourceEl = document.createElement('div');
        sourceEl.className = 'source-item';
        
        const title = source.title || `Paper ${index + 1}`;
        const url = source.url || '#';
        const authors = source.authors ? source.authors.join(', ') : 'Unknown authors';
        const published = source.published ? new Date(source.published).toLocaleDateString() : 'Date unknown';
        
        sourceEl.innerHTML = `
            <div class="source-title">
                [SOURCE ${index + 1}] ${title}
            </div>
            <div class="source-meta">
                Authors: ${authors}
            </div>
            <div class="source-meta">
                Published: ${published}
            </div>
            <div style="margin-top: 0.8rem;">
                <a href="${url}" target="_blank" style="color: #4a7ba7; text-decoration: none; font-weight: 500;">
                    View on arXiv →
                </a>
            </div>
        `;
        
        sourcesList.appendChild(sourceEl);
    });
}

// Show Status Message
function showStatus(element, message, type) {
    element.textContent = message;
    element.className = `status ${type}`;
    element.classList.remove('hidden');
    
    if (type !== 'loading') {
        setTimeout(() => {
            if (type === 'success') {
                element.classList.add('hidden');
            }
        }, 5000);
    }
}

// Show Collection Info
function showCollectionInfo(numPapers) {
    collectionInfo.innerHTML = `
        ✓ <strong>Collection Active:</strong> ${currentCollection} (${numPapers} papers indexed)
    `;
    collectionInfo.classList.remove('hidden');
}

// Reset UI
function resetUI() {
    searchQueryInput.value = '';
    questionQueryInput.value = '';
    answerBox.innerHTML = '';
    sourcesList.innerHTML = '';
    responseSection.classList.add('hidden');
    statusSearch.classList.add('hidden');
    statusQuestion.classList.add('hidden');
    collectionInfo.classList.add('hidden');
    currentCollection = null;
    
    searchQueryInput.focus();
}

// Initialize
window.addEventListener('DOMContentLoaded', () => {
    searchQueryInput.focus();
});
