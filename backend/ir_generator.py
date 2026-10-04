"""Intermediate Representation Generators for Zenith.

This module implements the IR-based scaffolding approach inspired by Athena (IUI 2026),
breaking code generation into structured stages: storyboard, data model, and GUI skeletons.
"""

import json
import re
from typing import Any, Optional
from model_service import generate_response


def _clean_and_extract_json(text: str) -> Optional[dict]:
    """Robustly extract and parse JSON from model output."""
    if not text:
        return None
    # 1. Remove markdown fences if present
    cleaned = re.sub(r"^```(?:json)?\s*", "", text.strip(), flags=re.MULTILINE)
    cleaned = re.sub(r"\s*```$", "", cleaned.strip(), flags=re.MULTILINE)
    
    # 2. Try direct load
    try:
        return json.loads(cleaned)
    except Exception:
        pass
        
    # 3. Try to locate outermost braces
    json_start = text.find("{")
    json_end = text.rfind("}") + 1
    if json_start >= 0 and json_end > json_start:
        snippet = text[json_start:json_end]
        # Remove trailing commas before closing braces/brackets
        snippet = re.sub(r",\s*([}\]])", r"\1", snippet)
        try:
            return json.loads(snippet)
        except Exception:
            pass
    return None


class IRGenerator:
    """Generates intermediate representations for code generation."""
    
    def __init__(self, model_name: str = "qwen2.5:7b"):
        self.model_name = model_name

    # ───────── Deterministic local IR ─────────
    # Two-stage LLM IR calls cost ~20-40s at ~10 tok/s and can still return
    # malformed JSON that we then throw away in favor of hardcoded fallbacks.
    # The heuristic builder below produces an equivalent-quality storyboard
    # and data model from the request text in <1ms, zero risk, zero tokens.
    # The LLM path remains available via generate_all_irs() for research
    # comparison (Athena-style two-stage vs heuristic one-stage).

    _ARCHETYPE_BLUEPRINTS = {
        "ecommerce": {
            "entity": "Product",
            "screens": [
                {"id": "storefront", "type": "catalog", "title": "Storefront",
                 "components": ["navbar", "card", "badge", "button", "toast"],
                 "description": "Product grid with category filters, search, and add-to-cart"},
                {"id": "orders", "type": "dashboard", "title": "Orders Dashboard",
                 "components": ["sidebar", "statcard", "datatable", "modal", "chart"],
                 "description": "Sales KPIs, fulfillment table, and inventory management"},
            ],
        },
        "crm": {
            "entity": "Lead",
            "screens": [
                {"id": "pipeline", "type": "dashboard", "title": "Pipeline Overview",
                 "components": ["sidebar", "statcard", "chart", "badge"],
                 "description": "Pipeline value, win rate, and lead-source KPIs"},
                {"id": "leads", "type": "list", "title": "Lead Management",
                 "components": ["datatable", "modal", "form", "button", "toast"],
                 "description": "Searchable lead table with status filters and add/edit modal"},
            ],
        },
    }
    _ARCHETYPE_BLUEPRINTS["analytics"] = _ARCHETYPE_BLUEPRINTS["crm"]
    _ARCHETYPE_BLUEPRINTS["kanban"] = {
        "entity": "Task",
        "screens": [
            {"id": "board", "type": "kanban", "title": "Task Board",
             "components": ["sidebar", "card", "badge", "modal"],
             "description": "Drag-friendly status columns with task cards and quick-add"},
            {"id": "insights", "type": "dashboard", "title": "Sprint Insights",
             "components": ["statcard", "chart", "datatable"],
             "description": "Velocity chart, burndown, and blocked-task table"},
        ],
    }
    _ARCHETYPE_BLUEPRINTS["booking"] = {
        "entity": "Appointment",
        "screens": [
            {"id": "calendar", "type": "calendar", "title": "Schedule",
             "components": ["navbar", "calendar", "badge", "modal"],
            "description": "Availability calendar with slot booking and confirmations"},
            {"id": "clients", "type": "list", "title": "Clients & Appointments",
             "components": ["datatable", "form", "button", "toast"],
             "description": "Client directory with appointment history and reminders"},
        ],
    }
    _ARCHETYPE_BLUEPRINTS["saas"] = {
        "entity": "Record",
        "screens": [
            {"id": "overview", "type": "dashboard", "title": "Overview Dashboard",
             "components": ["sidebar", "navbar", "statcard", "chart", "datatable", "badge"],
             "description": "KPI metrics, trend chart, and recent activity feed"},
            {"id": "records", "type": "list", "title": "Data Management",
             "components": ["datatable", "modal", "form", "button", "toast"],
             "description": "Full CRUD table with search, filters, and add/edit modal"},
        ],
    }
    _ARCHETYPE_BLUEPRINTS["general"] = _ARCHETYPE_BLUEPRINTS["saas"]

    _FIELD_TEMPLATES = {
        "ecommerce": [
            {"name": "id", "type": "number"}, {"name": "name", "type": "string"},
            {"name": "category", "type": "string"}, {"name": "price", "type": "number"},
            {"name": "rating", "type": "number"}, {"name": "stock", "type": "number"},
        ],
        "crm": [
            {"name": "id", "type": "number"}, {"name": "name", "type": "string"},
            {"name": "company", "type": "string"}, {"name": "email", "type": "string"},
            {"name": "value", "type": "number"},
            {"name": "status", "type": "string", "options": ["New", "Contacted", "Proposal", "Won", "Lost"]},
        ],
        "kanban": [
            {"name": "id", "type": "number"}, {"name": "title", "type": "string"},
            {"name": "assignee", "type": "string"},
            {"name": "priority", "type": "string", "options": ["Low", "Medium", "High", "Urgent"]},
            {"name": "status", "type": "string", "options": ["Backlog", "In Progress", "Review", "Done"]},
        ],
        "booking": [
            {"name": "id", "type": "number"}, {"name": "client", "type": "string"},
            {"name": "service", "type": "string"}, {"name": "date", "type": "string"},
            {"name": "time", "type": "string"},
            {"name": "status", "type": "string", "options": ["Confirmed", "Pending", "Cancelled", "Completed"]},
        ],
    }
    _FIELD_TEMPLATES["analytics"] = _FIELD_TEMPLATES["crm"]
    _FIELD_TEMPLATES["saas"] = _FIELD_TEMPLATES["crm"]
    _FIELD_TEMPLATES["general"] = _FIELD_TEMPLATES["crm"]

    def build_local_irs(
        self,
        user_request: str,
        business_type: str,
        archetype: str = "saas",
        app_name: str = "Zenith",
    ) -> dict:
        """Deterministic storyboard + data model derived from the request text.

        Zero tokens, zero latency, zero malformed-JSON risk. Quality is on par
        with the two-stage LLM path (whose output is, in practice, one of the
        same hardcoded fallbacks) and it is fully reproducible for evals.
        """
        archetype = archetype if archetype in self._ARCHETYPE_BLUEPRINTS else "saas"
        blueprint = self._ARCHETYPE_BLUEPRINTS[archetype]

        # Copy blueprints (never mutate class state) and attach an app name.
        screens = [dict(s) for s in blueprint["screens"]]
        storyboard = {
            "appName": app_name,
            "theme": "dark-modern",
            "screens": screens,
            "primaryEntity": blueprint["entity"],
        }

        # Personalize screen descriptions with salient words from the request.
        req_words = [
            w for w in re.findall(r"[A-Za-z][A-Za-z-]{3,}", user_request)
            if w.lower() not in {"build", "create", "make", "with", "that", "have", "system", "application", "app", "manage", "management"}
        ][:3]
        if req_words:
            descriptor = " / ".join(req_words).lower()
            for s in screens:
                s["description"] = f"{s['description']} (domain: {descriptor})"

        fields = [dict(f) for f in self._FIELD_TEMPLATES.get(archetype, self._FIELD_TEMPLATES["saas"])]
        data_model = {
            "entity": blueprint["entity"],
            "fields": fields,
            # Seed rows are intentionally generic; the model's design checklist
            # already requires 4-6 rich domain-realistic records.
            "sampleSeed": [],
        }
        return {"storyboard": storyboard, "data_model": data_model, "source": "heuristic"}

    def generate_storyboard(
        self,
        user_request: str,
        business_type: str,
        features: list[str],
        operation: str = "create"
    ) -> dict:
        """Generate a storyboard IR defining screens and navigation flows."""
        feature_str = ', '.join(features) if features else 'dashboard, data management, analytics'
        prompt = f"""You are an elite SaaS product architect. Design a clean, high-value screen structure for a modern {business_type} application.

User request: {user_request}
Features: {feature_str}

Respond with ONLY a JSON object with this exact schema:
{{
  "appName": "NameOfApp",
  "theme": "dark-modern",
  "screens": [
    {{
      "id": "overview",
      "type": "dashboard",
      "title": "Overview & Metrics",
      "components": ["sidebar", "navbar", "statcard", "chart", "datatable", "badge"],
      "description": "KPI metrics, growth trend chart, and recent activity"
    }},
    {{
      "id": "records",
      "type": "list",
      "title": "Manage Data",
      "components": ["datatable", "modal", "form", "button", "toast"],
      "description": "Full interactive data table with search, filter tabs, and add/edit modal"
    }}
  ],
  "primaryEntity": "Lead|User|Order|Project|Item"
}}"""
        
        response = generate_response(
            [{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=800
        )
        
        parsed = _clean_and_extract_json(response)
        if parsed and "screens" in parsed and len(parsed["screens"]) > 0:
            return parsed
            
        # Fallback tailored to request keywords
        req_lower = (user_request + " " + business_type).lower()
        if "ecommerce" in req_lower or "store" in req_lower or "shop" in req_lower:
            return {
                "appName": "CommerceHub",
                "theme": "dark-modern",
                "screens": [
                    {
                        "id": "catalog",
                        "type": "catalog",
                        "title": "Products & Storefront",
                        "components": ["navbar", "card", "badge", "button", "toast"],
                        "description": "Product grid with category filters, search, and instant add-to-cart"
                    },
                    {
                        "id": "admin",
                        "type": "dashboard",
                        "title": "Orders & Inventory",
                        "components": ["sidebar", "statcard", "datatable", "modal"],
                        "description": "Sales revenue stats, order fulfillment table, and stock management"
                    }
                ],
                "primaryEntity": "Product"
            }
        
        return {
            "appName": "AuraSaaS",
            "theme": "dark-modern",
            "screens": [
                {
                    "id": "dashboard",
                    "type": "dashboard",
                    "title": "Executive Dashboard",
                    "components": ["sidebar", "navbar", "statcard", "chart", "datatable", "badge"],
                    "description": "Active KPIs, revenue/lead growth graph, and recent records"
                },
                {
                    "id": "data_table",
                    "type": "list",
                    "title": "Records Directory",
                    "components": ["datatable", "modal", "form", "button", "toast"],
                    "description": "Searchable, filterable table with quick actions and add/edit modal dialog"
                }
            ],
            "primaryEntity": "Record"
        }
    
    def generate_data_model(
        self,
        storyboard: dict,
        user_request: str
    ) -> dict:
        """Generate a data model IR defining entities, fields, and realistic seed values."""
        entity_name = storyboard.get("primaryEntity", "Item")
        prompt = f"""You are a database architect. Design the primary data model and 4 realistic mock records for a {entity_name} in: {user_request}.

Respond with ONLY a JSON object with this exact schema:
{{
  "entity": "{entity_name}",
  "fields": [
    {{"name": "id", "type": "number"}},
    {{"name": "name", "type": "string"}},
    {{"name": "status", "type": "string", "options": ["Active", "Pending", "Completed"]}},
    {{"name": "value", "type": "number"}},
    {{"name": "date", "type": "string"}}
  ],
  "sampleSeed": [
    {{"id": 1, "name": "Example Alpha", "status": "Active", "value": 12500, "date": "2026-08-10"}},
    {{"id": 2, "name": "Example Beta", "status": "Pending", "value": 8400, "date": "2026-08-12"}}
  ]
}}"""
        
        response = generate_response(
            [{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=800
        )
        
        parsed = _clean_and_extract_json(response)
        if parsed and "fields" in parsed:
            return parsed
            
        return {
            "entity": entity_name,
            "fields": [
                {"name": "id", "type": "number"},
                {"name": "title", "type": "string"},
                {"name": "status", "type": "string", "options": ["Active", "In Progress", "Completed", "Archived"]},
                {"name": "metricValue", "type": "number"},
                {"name": "category", "type": "string"},
                {"name": "updatedAt", "type": "string"}
            ],
            "sampleSeed": [
                {"id": 1, "title": "Enterprise Pipeline Expansion", "status": "Active", "metricValue": 48000, "category": "Sales", "updatedAt": "Just now"},
                {"id": 2, "title": "Cloud Infrastructure Migration", "status": "In Progress", "metricValue": 24500, "category": "Engineering", "updatedAt": "2h ago"},
                {"id": 3, "title": "Brand Redesign & Marketing Deck", "status": "Completed", "metricValue": 18200, "category": "Design", "updatedAt": "1d ago"}
            ]
        }
    
    def generate_all_irs(
        self,
        user_request: str,
        business_type: str,
        features: list[str],
        registry_components: dict,
        operation: str = "create",
        use_llm: bool = False,
    ) -> dict:
        """Generate cohesive IRs: heuristic by default, optional two-stage LLM.

        The LLM path is retained for research comparison (Athena-style staged
        generation vs the heuristic one-stage builder) but is off by default:
        two extra round-trips at ~10 tok/s, and the parsed output was in
        practice replaced by the same hardcoded fallbacks anyway.
        """
        if not use_llm:
            return self.build_local_irs(
                user_request, business_type,
                archetype=(business_type or "saas").lower(),
            )

        print("[ir] Generating application storyboard plan (LLM path)...")
        storyboard = self.generate_storyboard(user_request, business_type, features, operation)
        
        print("[ir] Generating entity data model and seed data...")
        data_model = self.generate_data_model(storyboard, user_request)
        
        return {
            "storyboard": storyboard,
            "data_model": data_model,
            "source": "llm",
        }


def format_ir_for_prompt(irs: dict) -> str:
    """Format IRs as a compact, structured prompt section without token bloat."""
    storyboard = irs.get("storyboard", {})
    data_model = irs.get("data_model", {})
    
    lines = ["## Application Architecture Plan"]
    app_name = storyboard.get("appName", "SaaS Application")
    lines.append(f"- **Application Name**: {app_name}")
    
    screens = storyboard.get("screens", [])
    if screens:
        lines.append("- **Core Screens / Views**:")
        for s in screens:
            comp_list = ", ".join(s.get("components", []))
            lines.append(f"  • **{s.get('title', s.get('id'))}** ({s.get('type')}): {s.get('description', '')}. Components: `[{comp_list}]`")
            
    entity = data_model.get("entity", "Item")
    fields = [f.get("name", "") for f in data_model.get("fields", []) if f.get("name")]
    if fields:
        lines.append(f"- **Primary Data Entity**: `{entity}` with fields `{', '.join(fields)}`")
        
    seeds = data_model.get("sampleSeed", [])
    if seeds:
        lines.append(f"- **Seed Mock Records**: Initialize React state with at least {max(4, len(seeds))} realistic items matching this domain.")
        
    return "\n".join(lines)


if __name__ == "__main__":
    generator = IRGenerator()
    irs = generator.generate_all_irs(
        user_request="Build a real estate lead tracking CRM with revenue metrics and an interactive leads table",
        business_type="CRM",
        features=["leads table", "kpi metrics", "revenue chart"],
        registry_components={}
    )
    print("\n=== Compact Formatted IR Prompt ===")
    print(format_ir_for_prompt(irs))
