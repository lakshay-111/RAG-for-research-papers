# ArXiv RAG Website - Setup & Usage Guide

## ✅ What's Complete

### Backend (Flask API)
- ✅ `app.py` - Flask server with 4 REST API endpoints
- ✅ CORS support enabled for frontend integration
- ✅ `/api/search-arxiv` - Search and index papers
- ✅ `/api/ask` - Query papers with LLM
- ✅ `/api/get-collection` - Check collection status
- ✅ Source tracking with arXiv metadata (authors, published date, URL)

### Frontend
- ✅ `templates/index.html` - Semantic HTML structure
- ✅ `static/style.css` - Glassmorphism design (dark blue gradient, glass effects)
- ✅ `static/script.js` - Interactive functionality

### Core RAG System
- ✅ `rag.py` - Production-grade RAG with semantic chunking, query expansion, reranking
- ✅ ChromaDB vector database for persistent storage
- ✅ OpenRouter API integration (Google Gemma 2 9B-IT model)

## 🚀 How to Run

### 1. Install Dependencies (if not already done)
```bash
pip install -r requirements.txt
```

### 2. Set Environment Variables
Create or update `.env` file in the project root:
```
OPENROUTER_API_KEY=your_api_key_here
```

### 3. Start the Flask Server
```bash
python app.py
```
The server will start on `http://localhost:5000`

### 4. Open in Browser
Navigate to: **http://localhost:5000**

## 📋 How to Use the Website

### Step 1: Search Papers
1. Enter your search query (e.g., "machine learning security", "blockchain voting")
2. Choose search mode: **Relevance** (best matches) or **Latest** (newest papers)
3. Set number of papers to retrieve (1-10)
4. Click **"🔍 Search & Load Papers"** button
5. Wait for papers to be indexed (usually 1-2 minutes for 3 papers)

### Step 2: Ask Questions
1. Once papers are indexed, you'll see a green confirmation message
2. Type your question in the **"Ask your question"** textarea
3. Adjust number of chunks to retrieve (5-10 recommended)
4. Click **"📤 Get Answer"** button
5. The AI will provide a source-grounded answer with citations

### Step 3: View Results
- **Answer Box** - Shows the AI's response with source citations [SOURCE 1], [SOURCE 2], etc.
- **Sources Section** - Lists the papers used, with links to arXiv

### Start Over
- Click **"🔄 New Search"** to reset and search for different papers

## 🎨 Design Features

- **Glassmorphism UI** - Semi-transparent glass panels with backdrop blur
- **Dark Blue Gradient** - Professional dark blue color scheme (#1e3a5f to #2d5a8c)
- **Smooth Animations** - Slide-up transitions for panels
- **Responsive Design** - Works on desktop and tablet
- **Status Indicators** - Loading, success, and error states with visual feedback

## ⚙️ API Endpoints

### POST /api/search-arxiv
**Request:**
```json
{
  "query": "machine learning",
  "search_mode": "relevance",
  "num_papers": 3
}
```

**Response:**
```json
{
  "success": true,
  "collection_name": "arxiv_20240101_abc123",
  "message": "Successfully loaded 3 papers"
}
```

### POST /api/ask
**Request:**
```json
{
  "query": "What are the main findings?",
  "k": 5
}
```

**Response:**
```json
{
  "success": true,
  "answer": "Based on [SOURCE 1] and [SOURCE 2]...",
  "sources": [
    {
      "title": "Paper Title",
      "authors": ["Author 1", "Author 2"],
      "published": "2024-01-15",
      "url": "https://arxiv.org/abs/2401.xxxxx"
    }
  ],
  "num_sources": 2
}
```

## 🐛 Troubleshooting

**"Connection Refused"**
- Make sure Flask app is running on port 5000
- Check that no other app is using port 5000

**"No collection loaded"**
- You must search for papers first before asking questions
- Wait for the search to complete (look for green success message)

**"API Error"**
- Check your OPENROUTER_API_KEY in `.env`
- Make sure you have API credits available
- Check internet connection

**Papers not indexing**
- First-time indexing takes time (1-2 min for 3 papers)
- PDFs are being downloaded and processed
- Check console for detailed error messages

## 📁 File Structure
```
d:\Projects\RAG\
├── app.py                 # Flask backend
├── rag.py                 # RAG core engine
├── requirements.txt       # Python dependencies
├── templates/
│   └── index.html        # Frontend HTML
├── static/
│   ├── style.css         # Glassmorphism styling
│   └── script.js         # Frontend interactivity
└── chroma_db/            # Vector database storage
```

## 🔄 Workflow Example

1. User searches: "quantum computing algorithms"
2. Flask fetches 3 arXiv papers related to quantum computing
3. Papers are downloaded and text extracted
4. Text is split into semantic chunks (~500 words each)
5. Chunks are embedded and stored in ChromaDB
6. User asks: "What are the main quantum algorithms?"
7. Query is expanded with semantic variants
8. Top 5 relevant chunks are retrieved
9. LLM generates answer using only those chunks
10. Answer is displayed with source citations
11. User can click sources to view papers on arXiv

## 📞 Support

For issues or questions:
- Check FRONTEND_SETUP.md (this file)
- Review console output in Flask terminal
- Check browser developer console (F12) for client-side errors
