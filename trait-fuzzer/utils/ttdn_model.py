import logging
from dataclasses import dataclass, field
from typing import Dict, List, Set, Optional

@dataclass
class TTDNNode:
    name: str
    kind: str # "Trait", "Type", "Impl"
    children: Set[str] = field(default_factory=set) # Names of children nodes

class TTDNModel:
    """
    Type-Trait Dependency Network Model.
    Used to track complexity and detect stagnation.
    """
    def __init__(self):
        self.nodes: Dict[str, TTDNNode] = {}
        self.max_depth = 0
        self.cycles = 0

    def add_node(self, name: str, kind: str):
        if name not in self.nodes:
            self.nodes[name] = TTDNNode(name, kind)

    def add_edge(self, from_node: str, to_node: str):
        if from_node in self.nodes and to_node in self.nodes:
            self.nodes[from_node].children.add(to_node)
            # Re-calculate metrics when graph changes
            # For performance, maybe don't do this on every edge add if batching is possible
        else:
             logging.warning(f"Trying to add edge between non-existent nodes: {from_node} -> {to_node}")

    def calculate_complexity(self):
        """
        Calculates depth and cycle count.
        This is a simplified implementation. DFS for cycles and depth.
        """
        visited = set()
        recursion_stack = set()
        self.cycles = 0
        self.max_depth = 0
        
        def dfs(node_name: str, depth: int):
            visited.add(node_name)
            recursion_stack.add(node_name)
            
            self.max_depth = max(self.max_depth, depth)
            
            if node_name in self.nodes:
                for child in self.nodes[node_name].children:
                    if child not in visited:
                        dfs(child, depth + 1)
                    elif child in recursion_stack:
                        self.cycles += 1
            
            recursion_stack.remove(node_name)

        for node_name in self.nodes:
            if node_name not in visited:
                dfs(node_name, 1)
        
        return {
            "depth": self.max_depth,
            "cycles": self.cycles
        }

    def clear(self):
        self.nodes.clear()
        self.max_depth = 0
        self.cycles = 0

    def load_from_source(self, source_code: str):
        """
        Parse source code to populate the graph.
        Uses basic regex to find 'trait X', 'impl X for Y', 'trait X: Y'.
        """
        import re
        
        # Clear previous state? Or keep cumulative? 
        # For a fuzzer exploring one case, we usually want the graph of THAT case.
        self.clear()

        # Regex patterns
        # trait Foo
        trait_def_pattern = re.compile(r'trait\s+(\w+)')
        # trait Foo: Bar
        trait_inherit_pattern = re.compile(r'trait\s+(\w+)\s*:\s*(\w+)')
        # impl Foo for Bar
        impl_pattern = re.compile(r'impl\s+(\w+)\s+for\s+(\w+)')
        
        for line in source_code.splitlines():
            # Trait Definition
            match_def = trait_def_pattern.search(line)
            if match_def:
                trait_name = match_def.group(1)
                self.add_node(trait_name, "Trait")
                
            # Trait Inheritance (Supertraits)
            match_inherit = trait_inherit_pattern.search(line)
            if match_inherit:
                child_trait = match_inherit.group(1)
                parent_trait = match_inherit.group(2)
                self.add_node(child_trait, "Trait")
                self.add_node(parent_trait, "Trait")
                self.add_edge(child_trait, parent_trait)
                
            # Implementation
            match_impl = impl_pattern.search(line)
            if match_impl:
                trait_name = match_impl.group(1)
                type_name = match_impl.group(2)
                self.add_node(type_name, "Type")
                self.add_node(trait_name, "Trait")
                self.add_edge(type_name, trait_name) # Type depends on Trait behavior
