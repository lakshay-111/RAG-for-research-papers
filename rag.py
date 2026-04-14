import arxiv
import aiohttp
import asyncio
import PyPDF2
import io
import json
from asyncio import Semaphore
import chromadb
from chromadb.utils import embedding_functions
import os
from dotenv import load_dotenv
from openai import OpenAI
from termcolor import colored
import glob
from pathlib import Path
import docx
from tkinter import Tk, filedialog
import re
from typing import List, Dict, Tuple

# Optional dependencies
try:
    import tiktoken
    enc = tiktoken.get_encoding("cl100k_base")
except Exception as e:
    print(f"Warning: tiktoken not available: {e}")
    enc = None

# Reranker is optional - using simple scoring instead
reranker = None


# Load environment variables
load_dotenv()

openai_api_key = os.getenv("OPENROUTER_API_KEY")
if not openai_api_key:
    raise ValueError(
        "OPENROUTER_API_KEY is not set. Add it to a .env file or your system environment variables."
    )

# Initialize clients
client = chromadb.PersistentClient(path="./chroma_db")
arxiv_client = arxiv.Client()
openai_client = OpenAI(api_key=openai_api_key, base_url="https://openrouter.ai/api/v1")
default_ef = embedding_functions.DefaultEmbeddingFunction()

# ==================== UTILITY FUNCTIONS ====================

def count_tokens(text: str) -> int:
    """Count tokens in text for context window management."""
    if enc is None:
        # Fallback: estimate based on character count (rough approximation)
        return len(text) // 4
    return len(enc.encode(text))

def detect_paper_section(text: str) -> str:
    """Detect research paper section (abstract, intro, method, results, conclusion, references)."""
    text_lower = text.lower()
    
    if 'abstract' in text_lower[:500]:
        return 'abstract'
    elif any(x in text_lower[:1000] for x in ['introduction', 'background', 'related work']):
        return 'introduction'
    elif any(x in text_lower[:1000] for x in ['method', 'methodology', 'approach', 'algorithm']):
        return 'methodology'
    elif any(x in text_lower[:1000] for x in ['result', 'evaluation', 'experiment', 'findings']):
        return 'results'
    elif any(x in text_lower[:1000] for x in ['conclusion', 'discussion', 'future work']):
        return 'conclusion'
    elif 'reference' in text_lower or 'bibliography' in text_lower:
        return 'references'
    else:
        return 'body'

def semantic_chunk_text(text: str, max_chunk_tokens: int = 512, overlap_tokens: int = 100) -> List[str]:
    """
    Split text into chunks. Uses simple sentence-based approach for speed.
    """
    # Use simple character-based chunking for speed (no token counting overhead)
    chunk_size = 2000  # ~500 words per chunk
    overlap_size = 500
    
    chunks = []
    for i in range(0, len(text), chunk_size - overlap_size):
        chunk = text[i:i + chunk_size]
        if len(chunk.strip()) > 100:  # Filter tiny chunks
            chunks.append(chunk.strip())
    
    return chunks if chunks else [text]

async def fetch_pdf(session, url, semaphore):
    """Fetch PDF from URL with semaphore for rate limiting."""
    async with semaphore:
        try:
            async with session.get(url, timeout=30) as response:
                if response.status == 200:
                    return await response.read()
                else:
                    print(f"Failed to fetch {url}: HTTP {response.status}")
                    return None
        except Exception as e:
            print(f"Error fetching {url}: {e}")
            return None

async def extract_text_from_pdf(pdf_content) -> List[Tuple[str, str, int]]:
    """
    Extract text from PDF.
    Returns list of (text, section, page_number) tuples.
    """
    try:
        pdf_file = io.BytesIO(pdf_content)
        pdf_reader = PyPDF2.PdfReader(pdf_file)
        
        extracted_pages = []
        for page_num, page in enumerate(pdf_reader.pages):
            text = page.extract_text()
            if text.strip():
                section = detect_paper_section(text)
                extracted_pages.append((text, section, page_num))
        
        return extracted_pages
    except Exception as e:
        print(f"Error extracting PDF: {e}")
        return []

async def extract_text_from_docx(file_path) -> List[Tuple[str, str, int]]:
    """Extract text from Word document with section detection."""
    try:
        doc = docx.Document(file_path)
        full_text = "\n".join([para.text for para in doc.paragraphs])
        
        # Split into chunks and detect sections
        chunk_size = 2000
        chunks = []
        for i, chunk_start in enumerate(range(0, len(full_text), chunk_size)):
            chunk_text = full_text[chunk_start:chunk_start + chunk_size]
            if chunk_text.strip():
                section = detect_paper_section(chunk_text)
                chunks.append((chunk_text, section, i))
        
        return chunks if chunks else [(full_text, 'body', 0)]
    except Exception as e:
        print(f"Error extracting DOCX: {e}")
        return []

async def expand_query(query: str) -> List[str]:
    """
    Expand query with related terms for better retrieval.
    Uses simple keyword expansion and rephrasing.
    """
    expanded = [query]
    
    # Simple keyword-based expansion
    expansions = {
        'voting system': ['electronic voting', 'e-voting', 'digital ballot'],
        'machine learning': ['deep learning', 'neural networks', 'AI'],
        'security': ['cryptography', 'vulnerability', 'threat'],
        'algorithm': ['method', 'approach', 'technique'],
        'dataset': ['benchmark', 'corpus', 'data'],
    }
    
    for key, values in expansions.items():
        if key.lower() in query.lower():
            expanded.extend(values)
    
    return list(set(expanded))  # Remove duplicates

def rerank_chunks(query: str, chunks: List[Dict]) -> List[Dict]:
    """
    Simple reranking using query term frequency in chunks.
    Falls back to original order if no scoring method available.
    """
    if not chunks:
        return chunks
    
    # Simple keyword-based scoring
    query_terms = set(query.lower().split())
    
    def score_chunk(chunk: Dict) -> float:
        content_lower = chunk['content'].lower()
        # Count query term occurrences
        score = sum(content_lower.count(term) for term in query_terms)
        return score
    
    # Sort by score (descending)
    ranked = sorted([(chunk, score_chunk(chunk)) for chunk in chunks],
                   key=lambda x: x[1], reverse=True)
    
    return [chunk for chunk, score in ranked]

def format_citations(chunks: List[Dict]) -> str:
    """Format retrieved chunks with proper citations and metadata."""
    formatted = []
    
    for i, chunk in enumerate(chunks, 1):
        citation = (
            f"\n[SOURCE {i}] {chunk['metadata']['title']} "
            f"(Page {chunk['metadata'].get('page', '?')}, "
            f"Section: {chunk['metadata'].get('section', 'Unknown')})\n"
            f"---\n"
            f"{chunk['content']}\n"
        )
        formatted.append(citation)
    
    return "\n".join(formatted)

def create_informed_prompt(query: str, formatted_chunks: str, num_chunks: int) -> str:
    """
    Create a well-structured prompt with explicit grounding and uncertainty handling.
    """
    prompt = f"""You are an AI research assistant specialized in analyzing academic papers. 
Your task is to answer the following question based EXCLUSIVELY on the provided research paper excerpts.

IMPORTANT INSTRUCTIONS:
1. Answer ONLY based on the provided sources
2. If the provided chunks don't contain relevant information, explicitly state: "The provided sources do not contain sufficient information to answer this question."
3. If you find conflicting information, mention all perspectives and note the contradiction
4. Always cite your sources using [SOURCE X] format
5. If uncertain about any claim, express your confidence level (e.g., "Based on the sources, it appears that...")
6. Do NOT generate information not present in the sources
7. Highlight any limitations or gaps in the provided information

QUESTION: {query}

SOURCES ({num_chunks} most relevant chunks):
{formatted_chunks}

ANSWER:
"""
    return prompt

def estimate_context_usage(query: str, chunks: List[Dict], num_sources: int = 5) -> Dict:
    """Estimate token usage to avoid exceeding context limits."""
    query_tokens = count_tokens(query)
    
    # Estimate for GPT response (~1000 tokens typical)
    estimated_response = 1000
    
    # Count tokens in sources
    source_tokens = sum(count_tokens(chunk['content']) for chunk in chunks[:num_sources])
    
    # System message and formatting
    system_tokens = 500
    
    total_estimated = query_tokens + source_tokens + estimated_response + system_tokens
    max_tokens = 8000  # Conservative limit for gemma-2-9b
    
    return {
        'query_tokens': query_tokens,
        'source_tokens': source_tokens,
        'estimated_response': estimated_response,
        'total_estimated': total_estimated,
        'within_limit': total_estimated < max_tokens,
        'usage_percent': (total_estimated / max_tokens) * 100
    }



# ==================== MAIN WORKFLOW FUNCTIONS ====================

async def load_local_files(file_paths):
    """Load PDFs and Word documents from local paths with semantic chunking."""
    all_documents = {}
    
    for file_path in file_paths:
        file_path = Path(file_path)
        if not file_path.exists():
            print(f"File not found: {file_path}")
            continue
        
        file_name = file_path.name
        print(f"Processing: {file_name}")
        
        try:
            if file_path.suffix.lower() == '.pdf':
                with open(file_path, 'rb') as f:
                    pdf_content = f.read()
                pages = await extract_text_from_pdf(pdf_content)
                all_documents[file_name] = pages
            elif file_path.suffix.lower() == '.docx':
                pages = await extract_text_from_docx(file_path)
                all_documents[file_name] = pages
            else:
                print(f"Unsupported file format: {file_path.suffix}")
        except Exception as e:
            print(f"Error processing {file_name}: {e}")
    
    return all_documents

async def load_and_add_to_collection(collection_name):
    """Load local files and add them to ChromaDB collection with semantic chunking."""
    print("\nOpening file selection dialog...")
    
    root = Tk()
    root.withdraw()
    root.attributes('-topmost', True)
    
    file_paths = filedialog.askopenfilenames(
        title="Select PDF and Word documents",
        filetypes=[("PDF and Word files", "*.pdf *.docx"), ("All files", "*.*")]
    )
    
    root.destroy()
    
    if not file_paths:
        print("No files selected.")
        return None
    
    local_files = await load_local_files(list(file_paths))
    
    if not local_files:
        print("No valid files loaded.")
        return None
    
    collection = client.get_or_create_collection(name=collection_name, embedding_function=default_ef)
    
    paper_id = 0
    for file_name, pages in local_files.items():
        print(f"Adding {file_name} to collection with semantic chunking...")
        
        paper_data = {
            "title": file_name,
            "authors": ["Local Upload"],
            "summary": f"Locally uploaded document: {file_name}",
            "url": "local",
            "total_pages": len(pages)
        }
        
        # Semantic chunking
        chunk_id = 0
        for text, section, page_num in pages:
            semantic_chunks = semantic_chunk_text(text)
            
            for semantic_chunk in semantic_chunks:
                chunk_id += 1
                collection.add(
                    documents=[semantic_chunk],
                    metadatas=[{
                        "title": file_name,
                        "page": page_num,
                        "section": section,
                        "paper_id": f"local_{paper_id}",
                        "chunk_id": chunk_id
                    }],
                    ids=[f"local_paper_{paper_id}_page_{page_num}_chunk_{chunk_id}"]
                )
        
        # Save metadata
        json_file = "paper_metadata.json"
        if os.path.exists(json_file):
            with open(json_file, "r+") as file:
                data = json.load(file)
                data.append(paper_data)
                file.seek(0)
                json.dump(data, file, indent=4)
        else:
            with open(json_file, "w") as file:
                json.dump([paper_data], file, indent=4)
        
        print(f"Added to collection: {file_name} ({chunk_id} semantic chunks)")
        paper_id += 1
    
    print(f"Files added to collection: {collection_name}")
    return collection_name
async def search_arxiv(user_input, search_mode, n):
    """Search arXiv and add papers with semantic chunking."""
    try:
        sanitized_input = "".join(c if c.isalnum() or c in "-_" else "_" for c in user_input.lower())
        collection_name = f"arxiv_search_{sanitized_input}"[:50]
        collection_name = collection_name.rstrip("_-") or "arxiv_search_default"
        collection = client.get_or_create_collection(name=collection_name, embedding_function=default_ef)

        if search_mode in ['relevance', 'latest']:
            search = arxiv.Search(
                query=user_input,
                max_results=n,
                sort_by=arxiv.SortCriterion.SubmittedDate if search_mode == 'latest' else arxiv.SortCriterion.Relevance
            )
            results = list(arxiv_client.results(search))
        else:
            print("Invalid search mode. Please enter 'relevance' or 'latest'.")
            return None

        if not results:
            print("No results found for your query.")
            return None
        
        print(f"Found {len(results)} results. Downloading and processing...")
        
        semaphore = Semaphore(5)  # Reduce concurrent downloads to be respectful
        async with aiohttp.ClientSession() as session:
            tasks = [asyncio.create_task(fetch_pdf(session, result.pdf_url, semaphore)) for result in results]
            pdf_contents = await asyncio.gather(*tasks)

            async def process_paper(i, result, pdf_content):
                if pdf_content is None:
                    print(f"Skipping {result.title} - download failed")
                    return
                
                pages = await extract_text_from_pdf(pdf_content)
                if not pages:
                    print(f"Skipping {result.title} - no text extracted")
                    return
                
                paper_data = {
                    "title": result.title,
                    "authors": [author.name for author in result.authors],
                    "summary": result.summary,
                    "url": result.pdf_url,
                    "published": str(result.published),
                    "arxiv_id": result.entry_id.split('/abs/')[-1] if 'abs' in result.entry_id else result.entry_id,
                    "total_pages": len(pages)
                }
                
                # Semantic chunking for each page
                chunk_id = 0
                for text, section, page_num in pages:
                    semantic_chunks = semantic_chunk_text(text)
                    
                    for semantic_chunk in semantic_chunks:
                        chunk_id += 1
                        collection.add(
                            documents=[semantic_chunk],
                            metadatas=[{
                                "title": result.title,
                                "page": page_num,
                                "section": section,
                                "paper_id": f"paper_{i+1}",
                                "chunk_id": chunk_id,
                                "arxiv_id": paper_data["arxiv_id"]
                            }],
                            ids=[f"paper_{i+1}_page_{page_num}_chunk_{chunk_id}"]
                        )
                
                # Save metadata
                json_file = "paper_metadata.json"
                if os.path.exists(json_file):
                    with open(json_file, "r+") as file:
                        data = json.load(file)
                        data.append(paper_data)
                        file.seek(0)
                        json.dump(data, file, indent=4)
                else:
                    with open(json_file, "w") as file:
                        json.dump([paper_data], file, indent=4)
                
                print(f"✓ {result.title[:60]}... ({chunk_id} semantic chunks)")

            await asyncio.gather(*[process_paper(i, result, pdf_content) 
                                   for i, (result, pdf_content) in enumerate(zip(results, pdf_contents))])
        
        print(f"\nAll papers added to collection: {collection_name}")
        return collection_name
    
    except arxiv.ArxivError as e:
        print(f"An error occurred while searching arXiv: {e}")
        return None
    except Exception as e:
        print(f"An error occurred: {e}")
        return None

async def query_and_generate(collection_name: str, query: str, k: int = 5):
    """
    Improved RAG query with reranking, citation tracking, and context management.
    """
    collection = client.get_collection(name=collection_name, embedding_function=default_ef)
    
    # Query expansion for better retrieval
    print(colored("Expanding query for better retrieval...", "blue"))
    expanded_queries = await expand_query(query)
    
    # Multi-query retrieval
    all_results = []
    seen_ids = set()
    
    for expanded_q in expanded_queries[:3]:  # Limit expansion to avoid too many queries
        results = collection.query(
            query_texts=[expanded_q],
            n_results=min(k * 2, 20)  # Get more results for reranking
        )
        
        for doc, metadata, doc_id in zip(results['documents'][0], results['metadatas'][0], results['ids'][0]):
            if doc_id not in seen_ids:
                all_results.append({
                    'content': doc,
                    'metadata': metadata,
                    'id': doc_id
                })
                seen_ids.add(doc_id)
    
    # Rerank results for better relevance
    print(colored("Reranking results for relevance...", "blue"))
    ranked_results = rerank_chunks(query, all_results)
    top_chunks = ranked_results[:k]
    
    # Check context window
    context_info = estimate_context_usage(query, top_chunks, k)
    
    if not context_info['within_limit']:
        print(colored(f"⚠ Warning: Estimated token usage is {context_info['usage_percent']:.1f}% of limit. "
                     f"Reducing chunks.", "yellow"))
        top_chunks = ranked_results[:max(1, k // 2)]
    
    # Format citation-aware chunks
    print(colored(f"Formatting {len(top_chunks)} chunks with citations...", "blue"))
    formatted_chunks = format_citations(top_chunks)
    
    # Save retrieved chunks
    chunks_entry = {
        "query": query,
        "expanded_queries": expanded_queries,
        "num_chunks_retrieved": len(top_chunks),
        "context_usage": context_info,
        "chunks": [
            {
                "chunk_number": i+1,
                "title": chunk['metadata']['title'],
                "page": chunk['metadata'].get('page', '?'),
                "section": chunk['metadata'].get('section', 'unknown'),
                "content": chunk['content'][:1000]  # Store truncated for file size
            }
            for i, chunk in enumerate(top_chunks)
        ]
    }
    
    chunks_file = "retrieved_chunks.json"
    if os.path.exists(chunks_file):
        with open(chunks_file, "r+") as file:
            data = json.load(file)
            data.append(chunks_entry)
            file.seek(0)
            json.dump(data, file, indent=4)
    else:
        with open(chunks_file, "w") as file:
            json.dump([chunks_entry], file, indent=4)
    
    print(colored("\nTop Retrieved Chunks:", "cyan"))
    for i, chunk in enumerate(top_chunks, 1):
        print(colored(f"\n[{i}] {chunk['metadata']['title']} "
                     f"(Page {chunk['metadata'].get('page', '?')}, "
                     f"Section: {chunk['metadata'].get('section', 'unknown')})", "green"))
        print(chunk['content'][:300] + "...\n")
    
    # Create prompt with grounding
    prompt = create_informed_prompt(query, formatted_chunks, len(top_chunks))
    
    # Query LLM
    print(colored("Generating answer from LLM...\n", "blue"))
    
    response = openai_client.chat.completions.create(
        model="google/gemma-2-9b-it",
        temperature=0.3,  # Lower for more consistent, factual responses
        max_tokens=1500,
        stream=True,
        messages=[
            {
                "role": "system",
                "content": "You are an expert research assistant. Provide accurate, well-cited answers based only on provided sources. "
                          "Acknowledge limitations and uncertainties in your response."
            },
            {"role": "user", "content": prompt}
        ]
    )
    
    # Stream response
    print(colored("Response:\n", "cyan"))
    assistant_response = ""
    for chunk in response:
        if chunk.choices and chunk.choices[0].delta.content:
            content = chunk.choices[0].delta.content
            print(content, end="", flush=True)
            assistant_response += content
    
    print("\n")
    
    # Format response with markdown styling
    import re
    def format_output(text):
        # Replace **text** with bold
        text = re.sub(r'\*\*(.+?)\*\*', lambda m: colored(m.group(1), attrs=['bold']), text)
        # Replace * with bullet points
        text = re.sub(r'^\* ', lambda m: colored('● ', 'yellow'), text, flags=re.MULTILINE)
        return text
    
    # Re-print formatted version
    print(colored("\n--- Formatted Response ---\n", "cyan"))
    print(format_output(assistant_response))
    
    # Save Q&A
    qa_entry = {
        "question": query,
        "answer": assistant_response,
        "num_sources": len(top_chunks),
        "sources": [
            {
                "title": chunk['metadata']['title'],
                "page": chunk['metadata'].get('page', '?'),
                "section": chunk['metadata'].get('section', 'unknown'),
                "arxiv_id": chunk['metadata'].get('arxiv_id', 'N/A')
            }
            for chunk in top_chunks
        ]
    }
    
    qa_file = "qa_history.json"
    if os.path.exists(qa_file):
        with open(qa_file, "r+") as file:
            data = json.load(file)
            data.append(qa_entry)
            file.seek(0)
            json.dump(data, file, indent=4)
    else:
        with open(qa_file, "w") as file:
            json.dump([qa_entry], file, indent=4)
    
    print(colored(f"\n✓ Q&A saved to {qa_file}", "green"))


# ==================== MAIN ====================

print(colored("Welcome to Advanced ArXiv Research Paper RAG System!", "cyan"))

async def main():
    collection_name = None
    
    print(colored("\n=== Choose a Data Source ===", "cyan"))
    print(colored("1. Download from ArXiv", "green"))
    print(colored("2. Upload local PDF/Word documents", "green"))
    choice = input("Enter your choice (1 or 2): ")
    
    if choice == "1":
        while True:
            user_input = input(colored("\nEnter search query (or 'skip' to skip): ", "green"))
            if user_input.lower() == 'skip':
                break
            
            print(colored("\nSearch mode:", "blue"))
            print(colored("1. Relevance", "green"))
            print(colored("2. Latest", "green"))
            mode_choice = input("Enter choice: ")
            search_mode = "latest" if mode_choice == "2" else "relevance"
            
            n = int(input("Number of papers: "))
            collection_name = await search_arxiv(user_input, search_mode, n)
            
            if collection_name:
                break
    
    elif choice == "2":
        collection_name_input = input("Enter collection name: ")
        sanitized = "".join(c if c.isalnum() or c in "-_" else "_" for c in collection_name_input.lower())
        collection_name = f"local_{sanitized}"[:50].rstrip("_-") or "local_documents"
        collection_name = await load_and_add_to_collection(collection_name)
    
    else:
        print("Invalid choice.")
        return
    
    if not collection_name:
        print("No collection created.")
        return
    
    # Query loop
    while True:
        query = input(colored("\nEnter question (or 'quit' to exit): ", "yellow"))
        if query.lower() == 'quit':
            break
        
        try:
            k = int(input("Number of chunks to retrieve (default 5): ") or "5")
            k = max(1, min(k, 20))  # Limit between 1-20
        except ValueError:
            k = 5
        
        await query_and_generate(collection_name, query, k)

if __name__ == "__main__":
    asyncio.run(main())
