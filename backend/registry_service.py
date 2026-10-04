"""Component Registry Service for Zenith.

This service manages the component registry, providing lookup and formatting
capabilities for the IR-based code generation pipeline.
"""

import json
import os
from pathlib import Path
from typing import Any, Optional
from collections import defaultdict


class ComponentRegistry:
    """Manages component definitions for code generation."""
    
    def __init__(self, registry_path: Optional[str] = None):
        """Initialize the registry with a custom or default path."""
        if registry_path is None:
            registry_path = Path(__file__).parent / "registry"
        self.registry_path = Path(registry_path)
        self.components_path = self.registry_path / "components"
        self.patterns_path = self.registry_path / "patterns"
        
        self._cache = {}
        self._by_category = defaultdict(list)
        self._load_all()
    
    def _load_all(self):
        """Load all component definitions into memory."""
        if not self.components_path.exists():
            print(f"[registry] Components path not found: {self.components_path}")
            return
        
        for json_file in self.components_path.rglob("*.json"):
            try:
                with open(json_file, 'r', encoding='utf-8') as f:
                    component = json.load(f)
                    comp_id = component.get("id")
                    if comp_id:
                        self._cache[comp_id] = component
                        category = component.get("category", "uncategorized")
                        self._by_category[category].append(comp_id)
            except Exception as e:
                print(f"[registry] Error loading {json_file}: {e}")
        
        print(f"[registry] Loaded {len(self._cache)} components")
        for category, ids in self._by_category.items():
            print(f"[registry]   {category}: {len(ids)} components")
    
    def get(self, component_id: str) -> Optional[dict]:
        """Get a component by ID."""
        return self._cache.get(component_id)
    
    def get_by_category(self, category: str) -> list[dict]:
        """Get all components in a category."""
        return [self._cache[comp_id] for comp_id in self._by_category.get(category, [])]
    
    def search(self, query: str) -> list[dict]:
        """Search components by name, description, or ID."""
        query_lower = query.lower()
        results = []
        for comp_id, component in self._cache.items():
            if (query_lower in comp_id.lower() or
                query_lower in component.get("name", "").lower() or
                query_lower in component.get("description", "").lower()):
                results.append(component)
        return results
    
    def format_signatures_for_prompt(self, component_ids: list[str]) -> str:
        """Format concise component signatures for inclusion in LLM prompts without token bloat."""
        lines = []
        for comp_id in component_ids:
            comp = self.get(comp_id)
            if not comp:
                continue
            name = comp.get("name", comp_id)
            desc = comp.get("description", "")
            props = comp.get("props", {})
            props_str = ", ".join([f"{k}: {v.split('-')[0].strip()}" for k, v in props.items()]) if props else "children, className"
            examples = comp.get("usage_examples", [])
            example_str = f" Example: `{examples[0]}`" if examples else ""
            lines.append(f"- `<{name} {props_str} />` — {desc}.{example_str}")
        return "\n".join(lines)

    def build_registry_context(
        self,
        query_or_tags: list[str] | str,
        max_components: int = 6,
        max_chars: int = 2500,
    ) -> str:
        """Compact registry context for the generation prompt.

        Uses find_relevant_components + signature-only formatting so the
        registry finally participates in /api/generate without token bloat
        (full component sources would eat 3-8k chars each; signatures are
        ~60 chars). Trimmed to max_chars by the caller's budget manager.
        """
        ids = self.find_relevant_components(query_or_tags)[:max_components]
        if not ids:
            return ""
        header = (
            "## Component Registry (design-system primitives)\n"
            "Use these canonical building blocks where they fit your screens:\n"
        )
        return header + self.format_signatures_for_prompt(ids)

    def find_relevant_components(self, query_or_tags: list[str] | str) -> list[str]:
        """Find relevant component IDs based on query strings or tags."""
        matched = set()
        text = " ".join(query_or_tags).lower() if isinstance(query_or_tags, list) else query_or_tags.lower()
        
        # Always include base layout components
        matched.update(["container", "grid", "card", "button"])
        
        keyword_mappings = {
            "stat": "statcard",
            "kpi": "statcard",
            "metric": "statcard",
            "trend": "statcard",
            "table": "datatable",
            "list": "datatable",
            "record": "datatable",
            "data": "datatable",
            "chart": "chart",
            "graph": "chart",
            "analytics": "chart",
            "revenue": "chart",
            "nav": "navbar",
            "header": "navbar",
            "sidebar": "sidebar",
            "menu": "sidebar",
            "modal": "modal",
            "dialog": "modal",
            "popup": "modal",
            "tab": "tabs",
            "toast": "toast",
            "alert": "toast",
            "notification": "toast",
            "form": "form",
            "input": "input",
            "avatar": "avatar",
            "user": "avatar",
            "badge": "badge",
            "status": "badge",
            "skeleton": "skeleton",
            "loading": "skeleton",
        }
        
        for kw, comp_id in keyword_mappings.items():
            if kw in text and comp_id in self._cache:
                matched.add(comp_id)
                
        return sorted(matched)

    def format_for_prompt(self, component_ids: list[str], include_examples: bool = True) -> str:
        """Format components for inclusion in LLM prompts."""
        sections = []
        
        for comp_id in component_ids:
            component = self.get(comp_id)
            if not component:
                continue
            
            section = f"\n### {component.get('name', comp_id)}\n"
            section += f"ID: `{comp_id}`\n"
            section += f"Category: {component.get('category', 'unknown')}\n"
            section += f"Description: {component.get('description', '')}\n\n"
            
            # Component code
            section += "```jsx\n"
            section += component.get("component", "")
            section += "\n```\n\n"
            
            # Props
            if component.get("props"):
                section += "**Props:**\n"
                for prop, desc in component["props"].items():
                    section += f"- `{prop}`: {desc}\n"
                section += "\n"
            
            # Usage examples
            if include_examples and component.get("usage_examples"):
                section += "**Usage Examples:**\n"
                for example in component["usage_examples"]:
                    section += f"- `{example}`\n"
                section += "\n"
            
            sections.append(section)
        
        return "\n".join(sections)
    
    def get_component_code(self, component_id: str) -> Optional[str]:
        """Get just the component code for direct insertion."""
        component = self.get(component_id)
        return component.get("component") if component else None
    
    def get_design_tokens(self, component_id: str) -> dict:
        """Get design tokens for a component."""
        component = self.get(component_id)
        return component.get("design_tokens", {}) if component else {}
    
    def get_required_imports(self, component_ids: list[str]) -> set[str]:
        """Extract required imports from components."""
        imports = set()
        for comp_id in component_ids:
            component = self.get(comp_id)
            if component:
                code = component.get("component", "")
                # Simple import extraction
                if "import {" in code:
                    # Extract from lucide-react, react, etc.
                    for line in code.split("\n"):
                        if line.strip().startswith("import"):
                            imports.add(line.strip())
        return imports
    
    def list_categories(self) -> list[str]:
        """List all available categories."""
        return sorted(self._by_category.keys())
    
    def list_all(self) -> list[dict]:
        """List all components with basic info."""
        return [
            {
                "id": comp_id,
                "name": comp.get("name", comp_id),
                "category": comp.get("category", "unknown"),
                "description": comp.get("description", "")
            }
            for comp_id, comp in self._cache.items()
        ]


# Global registry instance
_registry: Optional[ComponentRegistry] = None


def get_registry() -> ComponentRegistry:
    """Get the global registry instance (singleton pattern)."""
    global _registry
    if _registry is None:
        _registry = ComponentRegistry()
    return _registry


def reload_registry():
    """Force reload the registry (useful for development)."""
    global _registry
    _registry = None
    return get_registry()


if __name__ == "__main__":
    # Test the registry
    registry = get_registry()
    
    print("\n=== Available Categories ===")
    for category in registry.list_categories():
        print(f"- {category}")
    
    print("\n=== All Components ===")
    for comp in registry.list_all():
        print(f"- [{comp['category']}] {comp['name']} ({comp['id']})")
    
    print("\n=== Button Component ===")
    button = registry.get("button")
    if button:
        print(f"Name: {button['name']}")
        print(f"Description: {button['description']}")
        print(f"\nCode:\n{button['component']}")
