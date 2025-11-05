# Epic 8: UI/UX Modernization

## Epic Goal

Modernize the Streamlit frontend to leverage v5.1 features, implementing a cohesive dark theme, modern interaction patterns, and improved user experience through declarative navigation, fragments, dialogs, and enhanced data editing capabilities.

## Stories

### Story 8.1: Foundation - Theme and Global Styling

**As a** system operator,
**I want** a modern, consistent dark theme with global styling primitives,
**so that** the application has a professional appearance and improved visual hierarchy.

**Acceptance Criteria:**
1. Create `.streamlit/config.toml` with dark theme configuration
2. Implement `src/ui/ui_styles.css` with card, pill, toolbar, and table styling primitives
3. Create `src/ui/ui_components.py` with reusable `card()` and `metric_compact()` helpers
4. Apply global CSS loading to all existing pages
5. Ensure all pages use `use_container_width=True` instead of deprecated `use_column_width`
6. Validate theme works across all existing pages without breaking functionality

### Story 8.2: Navigation Modernization

**As a** system operator,
**I want** declarative navigation with page links,
**so that** I can navigate between workflows more efficiently with a modern sidebar.

**Acceptance Criteria:**
1. Update `src/ui/app.py` to use `st.navigation` with `st.Page` definitions for all 7 pages
2. Add fallback navigation for older Streamlit versions
3. Implement strategic `st.page_link` cross-references in key workflows
4. Ensure page icons and titles are descriptive and consistent
5. Test navigation works both in development and production
6. Maintain existing page functionality while modernizing navigation

### Story 8.3: Interaction Patterns - Dialogs and Popovers

**As a** system operator,
**I want** modern confirmation dialogs and compact action menus,
**so that** critical operations have better UX and per-row actions are more accessible.

**Acceptance Criteria:**
1. Create `src/ui/helpers/dialogs.py` with `@st.dialog` wrappers for confirmations
2. Implement settlement confirmation dialog replacing two-click confirms
3. Create canonical event creation dialog in incoming bets workflow
4. Add `st.popover` per-row action menus in surebets and admin tables
5. Implement correction application dialog in reconciliation workflow
6. Add feature flags and fallbacks for older Streamlit versions
7. Ensure all dangerous operations require dialog confirmation

### Story 8.4: Performance - Fragments and Partial Reruns

**As a** system operator,
**I want** selective page reruns using fragments,
**so that** interactions in heavy tables and queues don't cause full page reloads.

**Acceptance Criteria:**
1. Create `src/ui/helpers/fragments.py` with `@st.fragment` decorators
2. Wrap incoming bets queue in fragment with `run_every=10` for auto-refresh
3. Isolate surebets table rendering in fragment for filtering performance
4. Implement fragment for reconciliation associate cards
5. Add fragment for streaming logs in export and statement generation
6. Ensure fragments maintain proper state management
7. Test performance improvements on large datasets

### Story 8.5: Data Editing Modernization

**As a** system administrator,
**I want** typed, validated data editors with modern table interactions,
**so that** CRUD operations are more intuitive and error-resistant.

**Acceptance Criteria:**
1. Refactor associate management to use `st.data_editor` with `column_config`
2. Update bookmaker management with typed select boxes and validation
3. Implement master-detail pattern with filtered bookmakers by associate selection
4. Add bulk selection capabilities for associate deactivation
5. Use `num_rows="fixed"` for strict CRUD control where appropriate
6. Implement proper read-only ID columns with disabled configuration
7. Add validation for share percentages, currency codes, and other constraints

### Story 8.6: Streaming and Progress Indicators

**As a** system operator,
**I want** real-time progress indicators and streaming output,
**so that** long-running operations provide clear feedback and status updates.

**Acceptance Criteria:**
1. Implement `st.write_stream` for OCR pipeline progress in incoming bets
2. Add streaming logs for export job progress with step-by-step feedback
3. Create `st.status` blocks for settlement and reconciliation operations
4. Implement `st.toast` notifications for successful coverage proof distribution
5. Add PDF preview capabilities using `st.pdf` for bet slips and monthly statements
6. Ensure proper error handling and status updates in all streaming workflows
7. Test streaming performance with various data sizes

### Story 8.7: Feature Flags and Version Compatibility

**As a** system maintainer,
**I want** comprehensive feature flagging for new Streamlit capabilities,
**so that** the application gracefully degrades on older Streamlit versions.

**Acceptance Criteria:**
1. Create `src/ui/utils/feature_flags.py` with comprehensive feature detection
2. Implement fallback patterns for all new features (fragment, dialog, popover, etc.)
3. Add version-specific conditional logic throughout the application
4. Test application functionality on Streamlit 1.30+ baseline
5. Document minimum version requirements and degraded functionality
6. Ensure core workflows remain functional even without modern features
7. Add upgrade recommendations in admin panel for outdated versions

### Story 8.8: UX Enhancements and Workflow Improvements

**As a** system operator,
**I want** improved workflow patterns and user experience enhancements,
**so that** daily operations are more efficient and error-resistant.

**Acceptance Criteria:**
1. Implement "Reset page state" helper for workflow recovery
2. Add advanced controls under `st.expander("Advanced")` for complex pages
3. Improve form submission patterns using `st.form` to prevent mid-typing reruns
4. Enhance resolve events triage with confidence indicators and bulk actions
5. Implement timezone-aware datetime display (UTC storage, Perth local display)
6. Add diagnostic tools under Admin → Advanced section
7. Ensure all destructive operations have clear confirmation flows
8. Validate that all pages follow consistent UX patterns

## Technical Assumptions

- Streamlit ≥ 1.46 recommended, with graceful fallbacks to ≥ 1.30
- Existing SQLite database structure remains unchanged
- Current page structure (7 main workflows) is maintained
- Component-based architecture with reusable helpers
- Feature-gated implementation for backward compatibility
- Dark theme as standard with consistent visual hierarchy

## Success Metrics

- Reduced page load times through fragment usage
- Improved user satisfaction with modern interaction patterns
- Decreased error rates in data editing operations
- Enhanced operational efficiency through better UX
- Maintained compatibility with older Streamlit versions
- Consistent visual design across all workflows

## Dependencies

- Existing Streamlit application foundation (epics 0-7)
- Frontend architecture v5.1 specification
- Streamlit-pdf package for PDF preview functionality
- Current UI components and page structure
