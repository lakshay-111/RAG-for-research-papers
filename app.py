from flask import Flask, render_template, request, jsonify
import asyncio
import json
import os
from rag import (
    search_arxiv, 
    load_and_add_to_collection, 
    query_and_generate,
    client,
    default_ef
)

app = Flask(__name__)
app.config['JSON_SORT_KEYS'] = False

# CORS support
@app.after_request
def add_cors_headers(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    return response

# Store current collection name
current_collection = None

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/search-arxiv', methods=['POST'])
def api_search_arxiv():
    """Search arXiv and add papers to collection"""
    try:
        data = request.json
        query = data.get('query', '')
        search_mode = data.get('search_mode', 'relevance')
        num_papers = int(data.get('num_papers', 5))
        
        if not query:
            return jsonify({'error': 'Query is required'}), 400
        
        # Run async search
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        collection_name = loop.run_until_complete(
            search_arxiv(query, search_mode, num_papers)
        )
        
        global current_collection
        current_collection = collection_name
        
        return jsonify({
            'success': True,
            'collection_name': collection_name,
            'message': f'Successfully loaded {num_papers} papers'
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/ask', methods=['POST'])
def api_ask():
    """Ask a question about retrieved papers"""
    try:
        data = request.json
        query = data.get('query', '')
        k = int(data.get('k', 5))
        
        if not query:
            return jsonify({'error': 'Query is required'}), 400
        
        if not current_collection:
            return jsonify({'error': 'No collection loaded. Search for papers first.'}), 400
        
        # Get current collection
        collection = client.get_collection(
            name=current_collection, 
            embedding_function=default_ef
        )
        
        # Retrieve relevant chunks
        results = collection.query(
            query_texts=[query],
            n_results=min(k, 10)
        )
        
        # Load paper metadata for sources
        paper_metadata_map = {}
        if os.path.exists('paper_metadata.json'):
            with open('paper_metadata.json', 'r') as f:
                papers = json.load(f)
                for paper in papers:
                    paper_metadata_map[paper.get('arxiv_id')] = paper
        
        # Format response
        chunks = []
        sources_set = set()
        sources = []
        
        for doc, metadata in zip(results['documents'][0], results['metadatas'][0]):
            chunks.append({
                'title': metadata.get('title', 'Unknown'),
                'page': metadata.get('page', '?'),
                'section': metadata.get('section', 'unknown'),
                'content': doc[:300] + '...'
            })
            
            # Get unique sources
            arxiv_id = metadata.get('arxiv_id')
            if arxiv_id and arxiv_id not in sources_set:
                sources_set.add(arxiv_id)
                
                # Get full metadata
                if arxiv_id in paper_metadata_map:
                    paper_info = paper_metadata_map[arxiv_id]
                    sources.append({
                        'title': paper_info.get('title', metadata.get('title', 'Unknown')),
                        'authors': paper_info.get('authors', []),
                        'published': paper_info.get('published', ''),
                        'url': f"https://arxiv.org/abs/{arxiv_id}",
                        'arxiv_id': arxiv_id
                    })
                else:
                    sources.append({
                        'title': metadata.get('title', 'Unknown'),
                        'authors': [],
                        'published': '',
                        'url': f"https://arxiv.org/abs/{arxiv_id}",
                        'arxiv_id': arxiv_id
                    })
        
        # Call LLM for answer
        from openai import OpenAI
        from dotenv import load_dotenv
        
        load_dotenv()
        openai_api_key = os.getenv("OPENROUTER_API_KEY")
        openai_client = OpenAI(api_key=openai_api_key, base_url="https://openrouter.ai/api/v1")
        
        # Format chunks for prompt
        formatted_chunks = "\n\n".join([
            f"[SOURCE {i+1}] {chunk['title']} (Page {chunk['page']}, Section: {chunk['section']})\n---\n{chunk['content']}"
            for i, chunk in enumerate(chunks)
        ])
        
        prompt = f"""You are an expert research assistant. Answer the following question based ONLY on the provided sources.

IMPORTANT:
- If sources don't contain relevant info, say so explicitly
- Always cite sources using [SOURCE X]
- Express uncertainty if appropriate

QUESTION: {query}

SOURCES ({len(chunks)} chunks):
{formatted_chunks}

ANSWER:"""
        
        response = openai_client.chat.completions.create(
            model="google/gemma-2-9b-it",
            temperature=0.3,
            max_tokens=1500,
            messages=[
                {
                    "role": "system",
                    "content": "You are an expert research assistant. Provide accurate, well-cited answers based only on provided sources."
                },
                {"role": "user", "content": prompt}
            ]
        )
        
        answer = response.choices[0].message.content
        
        return jsonify({
            'success': True,
            'answer': answer,
            'sources': sources,
            'num_sources': len(sources)
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/get-collection', methods=['GET'])
def api_get_collection():
    """Get current collection info"""
    if current_collection:
        return jsonify({
            'collection': current_collection,
            'loaded': True
        })
    return jsonify({
        'collection': None,
        'loaded': False
    })

if __name__ == '__main__':
    app.run(debug=True, port=5000)
