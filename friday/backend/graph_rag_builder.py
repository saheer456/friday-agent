import ast
import os
import json
from pathlib import Path

# Paths
BASE_DIR = Path(__file__).resolve().parent.parent
BACKEND_DIR = BASE_DIR / "backend"
DATA_DIR = BASE_DIR / "data"

class CodeGraphBuilder(ast.NodeVisitor):
    def __init__(self, filepath):
        self.filepath = filepath
        self.filename = os.path.basename(filepath)
        self.current_class = None
        self.current_function = None
        
        # Nodes and Edges
        self.nodes = []
        self.edges = []
        
        # Register the file node
        self.add_node(self.filename, "File", {"path": str(self.filepath)})

    def add_node(self, node_id, node_type, properties=None):
        properties = properties or {}
        if not any(n["id"] == node_id for n in self.nodes):
            self.nodes.append({
                "id": node_id,
                "type": node_type,
                "properties": properties
            })

    def add_edge(self, source, target, relationship):
        self.edges.append({
            "source": source,
            "target": target,
            "relationship": relationship
        })

    def visit_Import(self, node):
        for alias in node.names:
            module_name = alias.name
            self.add_node(module_name, "Module")
            self.add_edge(self.filename, module_name, "IMPORTS")
        self.generic_visit(node)

    def visit_ImportFrom(self, node):
        if node.module:
            self.add_node(node.module, "Module")
            self.add_edge(self.filename, node.module, "IMPORTS")
        self.generic_visit(node)

    def visit_ClassDef(self, node):
        class_id = f"{self.filename}:{node.name}"
        self.add_node(class_id, "Class", {"name": node.name})
        self.add_edge(self.filename, class_id, "CONTAINS")
        
        prev_class = self.current_class
        self.current_class = class_id
        self.generic_visit(node)
        self.current_class = prev_class

    def visit_FunctionDef(self, node):
        return self._handle_function(node)

    def visit_AsyncFunctionDef(self, node):
        return self._handle_function(node)

    def _handle_function(self, node):
        func_id = f"{self.current_class or self.filename}:{node.name}"
        self.add_node(func_id, "Function", {"name": node.name})
        
        if self.current_class:
            self.add_edge(self.current_class, func_id, "CONTAINS")
        else:
            self.add_edge(self.filename, func_id, "CONTAINS")
            
        prev_function = self.current_function
        self.current_function = func_id
        self.generic_visit(node)
        self.current_function = prev_function

    def visit_Call(self, node):
        if self.current_function:
            called_name = None
            if isinstance(node.func, ast.Name):
                called_name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                called_name = node.func.attr
                
            if called_name:
                called_id = f"{called_name}" # Simplified resolution
                self.add_edge(self.current_function, called_id, "CALLS")
                
        self.generic_visit(node)


def build_knowledge_graph():
    graph = {
        "nodes": [],
        "edges": []
    }
    
    # Target Python files in the root and backend directory
    python_files = list(BASE_DIR.glob("*.py")) + list(BACKEND_DIR.glob("*.py"))
    
    for filepath in python_files:
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                source = f.read()
            tree = ast.parse(source, filename=str(filepath))
            
            builder = CodeGraphBuilder(filepath)
            builder.visit(tree)
            
            graph["nodes"].extend(builder.nodes)
            graph["edges"].extend(builder.edges)
        except SyntaxError:
            print(f"Syntax error in {filepath.name}, skipping.")
        except Exception as e:
            print(f"Error processing {filepath.name}: {e}")

    # Deduplicate nodes and edges
    unique_nodes = {node["id"]: node for node in graph["nodes"]}.values()
    unique_edges = set()
    deduped_edges = []
    
    for edge in graph["edges"]:
        edge_tuple = (edge["source"], edge["target"], edge["relationship"])
        if edge_tuple not in unique_edges:
            unique_edges.add(edge_tuple)
            deduped_edges.append(edge)

    final_graph = {
        "nodes": list(unique_nodes),
        "edges": deduped_edges
    }

    os.makedirs(DATA_DIR, exist_ok=True)
    out_path = DATA_DIR / "code_knowledge_graph.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(final_graph, f, indent=2)
        
    print(f"Successfully generated Knowledge Graph at {out_path.relative_to(BASE_DIR)}")
    print(f"Total Nodes: {len(final_graph['nodes'])}")
    print(f"Total Edges: {len(final_graph['edges'])}")

if __name__ == "__main__":
    build_knowledge_graph()
