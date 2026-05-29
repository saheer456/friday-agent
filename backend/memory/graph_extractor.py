import json
import logging
import re
from typing import Dict, List, Tuple
from backend.providers.manager import provider_manager
from backend.memory.long_term import upsert_graph_node, add_graph_edge

logger = logging.getLogger("GraphExtractor")

SYSTEM_PROMPT = """You are an AI assistant designed to extract knowledge graphs from text.
Your task is to identify key entities (people, technologies, projects, preferences, tasks, or concepts) and the relationships between them.

For the given chat interaction between "User" and "Assistant", output a JSON object containing a list of "nodes" and "edges".

Guidelines for Nodes:
1. "id": A unique, concise, lowercase identifier using snake_case (e.g., "sqlite", "saheer_khan", "python").
2. "name": The natural name of the entity (e.g., "SQLite", "Saheer Khan", "Python").
3. "type": The entity type. Choose from: Person, Technology, Project, Preference, Task, Concept, Organization, or File.
4. "description": A short explanation of the entity's significance or context in this conversation.

Guidelines for Edges:
1. "source": The ID of the source node.
2. "target": The ID of the target node.
3. "relation": The relationship verb in uppercase, snake_case (e.g., "PREFERS", "DEVELOPED_BY", "USES", "IMPLEMENTS", "CONTAINS", "BLOCKED_BY").
4. "weight": A float from 0.0 to 1.0 indicating relevance or strength (default: 1.0).

Do not extract casual conversation or pleasantries. Focus only on factual knowledge, user preferences, projects, technologies, and tasks.

Return ONLY a valid JSON object in the following format:
{
  "nodes": [
    {"id": "user", "name": "User", "type": "Person", "description": "The user interacting with Friday"},
    {"id": "sqlite", "name": "SQLite", "type": "Technology", "description": "A local relational database"}
  ],
  "edges": [
    {"source": "user", "target": "sqlite", "relation": "PREFERS", "weight": 0.8}
  ]
}
Do not include any pre-text, post-text, or markdown formatting (except standard JSON codeblocks if necessary).
"""

# Simple canonicalization map for common technology/project names
CANONICAL_IDS = {
    "sqlite3": "sqlite",
    "sqlite_db": "sqlite",
    "sqlite_database": "sqlite",
    "postgres": "postgresql",
    "postgres_db": "postgresql",
    "postgres_database": "postgresql",
    "supa_base": "supabase",
    "supabasedb": "supabase",
    "python_language": "python",
    "py": "python",
    "js": "javascript",
    "ts": "typescript",
    "reactjs": "react",
    "nextjs": "next",
    "tailwind": "tailwindcss",
    "css3": "css",
    "html5": "html",
    "sir": "user",
    "assistant": "friday",
    "friday_agent": "friday"
}

def canonicalize_id(entity_id: str) -> str:
    """Normalize IDs to lowercase snake_case and map synonyms."""
    # Clean and lowercase
    clean = re.sub(r'[^a-zA-Z0-9_\-]', '', entity_id.strip().lower().replace(" ", "_"))
    return CANONICAL_IDS.get(clean, clean)

async def extract_and_save_graph(text: str) -> bool:
    """
    Extract entities and relationships from the text and save them to the database.
    """
    try:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Extract entities and relationships from the following text:\n\n{text}"}
        ]
        
        response = await provider_manager.generate(messages, is_heavy=False)
        content = response.content.strip()
        
        # Clean markdown codeblock formatting if present
        if content.startswith("```"):
            # Strip first line (e.g. ```json or ```) and trailing ```
            lines = content.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            content = "\n".join(lines).strip()
            
        data = json.loads(content)
        
        nodes = data.get("nodes", [])
        edges = data.get("edges", [])
        
        if not nodes and not edges:
            logger.debug("No nodes or edges extracted from the text.")
            return False
            
        # Map of node_id -> node for lookup
        node_map = {}
        
        # Save Nodes
        for n in nodes:
            orig_id = n.get("id")
            if not orig_id:
                continue
            norm_id = canonicalize_id(orig_id)
            name = n.get("name", orig_id)
            node_type = n.get("type", "Concept")
            description = n.get("description", "")
            
            # Save to DB
            await upsert_graph_node(norm_id, name, node_type, description)
            node_map[norm_id] = {"id": norm_id, "name": name, "type": node_type}
            
        # Save Edges
        for e in edges:
            src = e.get("source")
            tgt = e.get("target")
            rel = e.get("relation")
            weight = float(e.get("weight", 1.0))
            
            if not src or not tgt or not rel:
                continue
                
            norm_src = canonicalize_id(src)
            norm_tgt = canonicalize_id(tgt)
            norm_rel = rel.strip().upper().replace(" ", "_")
            
            # Ensure the source and target nodes exist in the DB (even with default values)
            if norm_src not in node_map:
                await upsert_graph_node(norm_src, src.title(), "Concept", f"Referenced in relation: {norm_rel}")
                node_map[norm_src] = {"id": norm_src}
            if norm_tgt not in node_map:
                await upsert_graph_node(norm_tgt, tgt.title(), "Concept", f"Referenced in relation: {norm_rel}")
                node_map[norm_tgt] = {"id": norm_tgt}
                
            # Save edge to DB
            await add_graph_edge(norm_src, norm_tgt, norm_rel, weight)
            
        logger.info(f"Successfully extracted and saved {len(nodes)} nodes and {len(edges)} edges to the graph.")
        return True
        
    except json.JSONDecodeError as je:
        logger.warning(f"Failed to parse JSON response from LLM extractor: {je}. Raw: {content}")
        return False
    except Exception as e:
        logger.error(f"Failed to extract/save graph: {e}", exc_info=True)
        return False
