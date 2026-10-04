# Registry-Based UI Generation with IR Scaffolding for 7B Models

## Research Foundation

This approach combines two validated techniques from recent literature:

### 1. Component Registry Assembly (CHI EA 2026)
- **Paper**: "Design System-Compliant User Interface Generation with LLM Agents: A Comparative Study of Context Engineering Strategies"
- **Finding**: Registry-based component assembly achieved 95.08% design system compliance, outperforming prompt-embedding and RAG-style snippet injection
- **Key insight**: Pre-built component registry reduces cognitive load on the model by providing validated building blocks

### 2. Intermediate Representation Scaffolding (Athena, IUI 2026)
- **Paper**: "Athena: Intermediate Representations for Iterative Scaffolded App Generation with an LLM" (Apple Research)
- **Finding**: IR-based scaffolding (storyboards, data models, GUI skeletons) produced organized multi-file code; 75% of users preferred it over chatbot-style baseline
- **Key insight**: Breaking generation into structured stages reduces error rates and improves organization

### 3. Our Novel Contribution
- **Gap**: Neither paper targets 7B-class local models on gaming laptops (RTX 3050 6GB)
- **Contribution**: Combining registry+IR specifically for React/Tailwind generation under hardware constraints
- **Additional**: Self-improvement loop from user corrections (SEAL-inspired ADR pattern)

## System Architecture

### Stage 1: Component Registry
```
registry/
├── components/
│   ├── layout/
│   │   ├── container.json
│   │   ├── grid.json
│   │   └── sidebar.json
│   ├── ui/
│   │   ├── button.json
│   │   ├── card.json
│   │   ├── input.json
│   │   └── modal.json
│   ├── navigation/
│   │   ├── navbar.json
│   │   └── tabs.json
│   └── data/
│       ├── table.json
│       ├── chart.json
│       └── stat.json
└── patterns/
    ├── dashboard.json
    ├── landing.json
    └── admin.json
```

Each component definition includes:
- React component code (with Tailwind classes)
- Props interface
- Usage examples
- Design tokens (colors, spacing)
- Accessibility attributes

### Stage 2: Intermediate Representations

#### IR 1: Storyboard Graph
```json
{
  "screens": [
    {
      "id": "landing",
      "type": "landing",
      "components": ["hero", "features", "pricing", "cta"],
      "navigation": ["navbar", "footer"]
    },
    {
      "id": "dashboard",
      "type": "dashboard",
      "components": ["sidebar", "stats", "chart", "table"],
      "navigation": ["navbar"]
    }
  ],
  "flows": [
    {"from": "landing", "to": "dashboard", "trigger": "login"}
  ]
}
```

#### IR 2: Data Model
```json
{
  "entities": [
    {
      "name": "User",
      "fields": [
        {"name": "id", "type": "string"},
        {"name": "name", "type": "string"},
        {"name": "email", "type": "string"}
      ]
    }
  ],
  "relationships": []
}
```

#### IR 3: GUI Skeletons
```json
{
  "screens": {
    "landing": {
      "layout": "container",
      "sections": [
        {"component": "hero", "props": {...}},
        {"component": "features", "props": {...}}
      ]
    }
  }
}
```

### Stage 3: Code Generation Pipeline

1. **User Request** → Extract requirements
2. **Storyboard Generation** → Plan screens and navigation
3. **Data Model Generation** → Define entities and relationships
4. **GUI Skeleton Generation** → Map components to screens
5. **Registry Lookup** → Fetch component implementations
6. **Code Assembly** → Generate final React files
7. **Validation** → Check imports, syntax, design compliance
8. **User Feedback Loop** → Capture corrections for registry updates

## Implementation Plan

### Phase 1: Component Registry (Immediate)
- [ ] Create registry structure
- [ ] Implement core UI components (button, card, input)
- [ ] Implement layout components (container, grid)
- [ ] Implement navigation components (navbar, sidebar)
- [ ] Add registry lookup service

### Phase 2: IR Generation (Next)
- [ ] Implement storyboard generator
- [ ] Implement data model generator
- [ ] Implement GUI skeleton generator
- [ ] Add IR validation

### Phase 3: Pipeline Integration (Next)
- [ ] Modify `/api/generate` to use IR pipeline
- [ ] Add registry-aware code generation
- [ ] Implement multi-stage generation
- [ ] Add streaming support for IR stages

### Phase 4: Self-Improvement (Future)
- [ ] Capture user corrections
- [ ] Implement ADR pattern for registry updates
- [ ] Add component usage analytics
- [ ] Implement automatic registry refinement

## Hardware Optimization

### Context Window Management
- Stage 1 (Storyboard): ~2000 tokens
- Stage 2 (Data Model): ~1500 tokens
- Stage 3 (GUI Skeletons): ~2500 tokens
- Stage 4 (Code Assembly): ~4000 tokens
- Total: ~10K tokens (fits in 16K context with margin)

### Component Selection Strategy
- Lazy loading: Only load components needed for current screen
- Caching: Cache frequently used components in memory
- Compression: Use minimal component descriptions in prompts

### Quantization Strategy
- Use Q4_K_M for base model (already configured)
- Registry components stored as plain text (no quantization needed)
- IRs stored as compact JSON

## Evaluation Metrics

### Design Compliance
- Component registry usage rate
- Design system adherence (manual audit)
- Visual consistency score

### Code Quality
- Import resolution success rate
- Syntax error rate
- Component reusability score

### User Experience
- Generation time (target: <30s for full app)
- User satisfaction (feedback rating)
- Iteration count (target: <3 to reach satisfactory result)

## References

1. Design System-Compliant User Interface Generation with LLM Agents: A Comparative Study of Context Engineering Strategies. CHI EA 2026.
2. Athena: Intermediate Representations for Iterative Scaffolded App Generation with an LLM. IUI 2026.
3. Context Engineering 2.0: The Context of Context Engineering. arXiv 2025.
