# Epic 7: System Administration

**Status:** Draft
**Priority:** P0 (Blocker for Epics 2-6)
**Estimated Duration:** 4-6 days
**Owner:** Tech Lead
**Phase:** 4 (System Administration)

---

## Epic Goal

Build a comprehensive web-based associate management system that provides role-based access control, and enables seamless administration of users, bookmakers, and permissions. This epic establishes an administrative foundation that works alongside the existing Telegram bot system, providing enhanced management capabilities while maintaining current functionality.

---

## Business Value

### Operator Benefits
- **Web Interface**: Provides modern web-based associate management alongside existing Telegram bot
- **Efficiency**: Bulk operations, search/filter capabilities, visual management
- **Audit Trail**: Complete change tracking with timestamps and user attribution
- **Role-Based Security**: Admin controls vs. partner self-service
- **Dual System Support**: Both web and Telegram systems operational

### System Benefits
- **Scalable Administration**: Web interface scales better than bot commands
- **Data Integrity**: Centralized associate management with audit trails
- **Integration Ready**: Clean API endpoints for bet ingestion workflows
- **Compliance**: Proper access controls and audit capabilities
- **Backward Compatibility**: Existing Telegram functionality preserved

**Success Metric**: Web-based associate management fully operational while Telegram system continues working, with seamless integration between both systems.

---

## Epic Description

### Context

Current associate management is limited to Telegram bot commands:
- `/register` - Manual admin registration of chat IDs
- `/help` - Basic command listing
- No web interface for viewing or managing associates
- No bulk operations or search capabilities
- Limited audit trail of changes

### What's Being Built

Six interconnected components:

1. **Associate Management UI** (Story 7.1)
   - Web-based CRUD interface for associate operations
   - Search, filter, and bulk operations
   - Role-based access control (Admin vs Partner)
   - Integration with existing Telegram system

2. **Role-Based Access Control** (Story 7.2)
   - Authentication system with role permissions
   - Admin users can manage all associates
   - Partners can only manage their own bookmakers

3. **Bookmaker Assignment Management** (Story 7.3)
   - Associate-bookmaker relationship management
   - Multiple bookmakers per associate
   - Assignment history and audit trail

4. **Dual System Integration** (Story 7.4)
   - Seamless integration between web and Telegram systems
   - Unified associate data accessible from both interfaces
   - Registration source tracking (web vs Telegram)

5. **Event Catalog & Normalization Admin** (Story 7.5)
   - Browse/search canonical events (filters: sport, date, pair key)
   - "Merge Events" tool (reassign bets/surebets, then delete source)
   - Display and recompute pair key (team1_slug/team2_slug) from normalized names
   - Bet rebinding suggestions (pair key first, then strict fuzzy) with one‑click rebind
   - Team alias management: view/edit `data/team_aliases.json`; reload without restart

6. **Maintenance & Dev Tools** (Story 7.6)
   - One‑click DB reset (dev) with optional screenshots/logs/exports purge
   - Rebuild indexes, run schema validation, backfill pair keys for legacy rows
   - Health checks (storage, DB, alias load, OpenAI key present)

### Integration Points

**Upstream Dependencies:**
- Epic 0 (Foundation): Database schema, authentication patterns
- Epic 1 (Bet Ingestion): Associate selection integration points

**Downstream Consumers:**
- Epic 2 (Bet Review): Enhanced associate selection in review workflow
- Epic 3 (Surebet Matching): Associate filtering in matching dashboard
- Epic 4 (Settlement): Associate attribution in settlement calculations
- Epic 5 (Reconciliation): Associate-level reporting and reconciliation
- Epic 6 (Reporting): Associate management reports and analytics

---

## Stories

### Story 7.1: Associate Management UI

**As a system administrator**, I want a web-based interface to manage associates so I can perform CRUD operations while keeping the existing Telegram system functional.

**Acceptance Criteria:**
- [ ] "Associate Management" Streamlit page with full CRUD interface:
  - **Associate List**: Table showing all associates with:
     - Display alias, role (Admin/Partner), status (Active/Inactive), created date
     - Search/filter by alias, role, status
     - Registration source indicator (Web/Telegram)
     - Pagination for >50 associates
  - **Add Associate Form**:
     - Display alias (required, unique)
     - Role dropdown: Admin, Partner (default: Partner)
     - Status toggle: Active, Inactive (default: Active)
     - Optional notes field
     - "Save Associate" button with validation
  - **Edit Associate**: Click-to-edit any associate in list
     - Pre-populate form with existing data
     - Role change restricted to admins (Partners cannot change their own role to Admin)
     - **Delete Associate**: Delete button with confirmation dialog
     - Only admins can delete associates
     - Soft delete (status=Inactive) with audit trail
  - [ ] **Bookmaker Management per Associate**:
  - Expand associate row to show assigned bookmakers
  - "Add Bookmaker" button for each associate
  - Bookmaker form: name, currency, status (Active/Inactive)
  - Edit/delete individual bookmakers
  - Visual indicators for bookmaker count per associate
  - [ ] **Bulk Operations**:
  - "Add Multiple Associates" button
  - CSV upload template for bulk associate creation
  - Bulk status changes (activate/deactivate multiple associates)
  - [ ] **Real-time Updates**:
  - Changes reflect immediately without page reload
  - Success/error toast notifications
  - Conflict detection (duplicate alias validation)
  - [ ] **Mobile Responsive**:
  - Functional on mobile devices
  - Touch-friendly buttons and forms
  - Collapsible sections for small screens
  - [ ] **Telegram Integration**:
  - Display Telegram registration status for each associate
  - Link to Telegram chat ID if registered via Telegram
  - Synchronize data between web and Telegram systems

**Technical Notes:**
- Use `st.data_editor` for associate list with inline editing
- Implement role-based UI conditional rendering
- Database operations through service layer (`src/services/associate_management.py`)
- Follow existing UI patterns from Epic 1-3 stories
- Cache associate list with TTL=30s for performance
- Integrate with existing Telegram bot system for data synchronization

---

### Story 7.2: Role-Based Access Control & Security

**As a system administrator**, I want role-based access control so partners can only manage their own data while admins have full system access, while maintaining compatibility with existing Telegram authentication.

**Acceptance Criteria:**
- [ ] **Authentication System**:
  - Login page with username/password authentication
  - Session management with timeout (30 minutes)
  - "Remember me" option for trusted devices
  - Logout functionality with session cleanup
  - Integration with existing Telegram authentication (if applicable)
- [ ] **Role-Based Permissions**:
  - Add `role` field to `associates` table: 'admin', 'partner'
  - UI adapts based on user role:
    - **Admin users**: Can create, edit, delete any associate; can manage all bookmakers
    - **Partner users**: Can only edit their own associate record; can only manage their assigned bookmakers
  - Permission checks in all associate management operations
- [ ] **Security Features**:
  - Password hashing with secure storage (bcrypt)
  - Rate limiting on login attempts (5 attempts per 15 minutes)
  - Session token validation on all protected pages
  - Audit logging of all login attempts and permission changes
- [ ] **Admin User Management**:
  - Separate admin user management (distinct from associates)
  - Admin users can manage other admin users
  - Initial admin user created during setup
- [ ] **UI Security Indicators**:
  - Visual indicators of current user role
  - Permission-denied messages for unauthorized actions
  - Secure logout with confirmation dialog
- [ ] **Telegram Compatibility**:
  - Existing Telegram bot authentication remains functional
  - Web authentication can optionally use Telegram credentials for verification
  - Clear separation between web and Telegram authentication systems

**Technical Notes:**
- Extend existing authentication patterns from Epic 0
- Add `admin_users` table for admin user management
- Implement middleware for role-based access control
- Use Streamlit session state for user authentication
- Follow security best practices from architecture docs
- Maintain compatibility with existing Telegram bot system

---

### Story 7.3: Bookmaker Assignment Management

**As a system administrator**, I want to manage bookmaker assignments for associates so each partner can have multiple bookmaker accounts properly configured while maintaining integration with existing systems.

**Acceptance Criteria:**
- [ ] **Bookmaker CRUD Operations**:
  - Add new bookmaker to associate
  - Edit existing bookmaker details (name, currency, status)
  - Deactivate bookmaker (soft delete with status=Inactive)
  - Delete bookmaker (hard delete with audit trail)
- [ ] **Assignment Interface**:
  - Associate selection dropdown (filtered by role and status)
  - Bookmaker list per selected associate
  - Drag-and-drop reordering of bookmaker priority
  - Bulk assignment (multiple bookmakers to multiple associates)
- [ ] **Bookmaker Details**:
  - Bookmaker name, display name, currency supported
  - API credentials (if applicable) with secure storage
  - Status (Active/Inactive), commission rates (if applicable)
  - Integration status (connected/disconnected indicators)
  - Telegram integration status (if bookmaker has Telegram bot)
- [ ] **Assignment History**:
  - Log all bookmaker assignment changes
  - Track which admin made changes and when
  - Export assignment history for audit purposes
- [ ] **Validation Rules**:
  - Associate must be Active to receive bookmaker assignments
  - Bookmaker names must be unique within system
  - Currency validation against supported currencies
  - Cannot assign inactive bookmakers to active associates
- [ ] **Telegram Integration**:
  - Display Telegram bot status for each bookmaker
  - Link bookmaker assignments to Telegram chat IDs where applicable
  - Synchronize bookmaker data between web and Telegram systems

**Technical Notes:**
- Create `bookmaker_assignments` table linking associates to bookmakers
- Implement service layer for assignment operations
- Add audit trail for all assignment changes
- Integration with existing associate management UI
- Maintain compatibility with existing Telegram bot system

---

### Story 7.4: Dual System Integration

**As a system administrator**, I want seamless integration between the new web-based associate management system and the existing Telegram bot system so both can operate simultaneously with synchronized data.

**Acceptance Criteria:**
- [ ] **Data Synchronization**:
  - Web and Telegram systems share common associate data
  - Changes in web system reflect in Telegram system (where applicable)
  - Changes in Telegram system reflect in web system
  - Conflict resolution for simultaneous changes
- [ ] **Unified Associate View**:
  - Single source of truth for associate data
  - Registration source tracking (Web vs Telegram)
  - Bidirectional data synchronization between systems
- [ ] **Registration Source Management**:
  - Clear indicators showing how each associate was registered
  - Ability to switch registration source for existing associates
  - Unified authentication across both systems
- [ ] **Bet Ingestion Integration**:
  - Bet ingestion can accept associates from both registration sources
  - Associate selection dropdown shows all associates regardless of registration source
  - Clear audit trail showing which system was used for each operation
- [ ] **Fallback Mechanism**:
  - If web system is unavailable, Telegram system remains functional
  - If Telegram system is unavailable, web system remains functional
  - Automatic failover between systems when needed
- [ ] **Monitoring Dashboard**:
  - Display registration source distribution (Web vs Telegram)
  - System health indicators for both web and Telegram
  - Synchronization status and error tracking
- [ ] **Gradual Transition Support**:
  - Ability to phase out Telegram registration when ready
  - Data migration tools for moving from Telegram-only to web-only
  - Clear transition timeline and milestones

**Technical Notes:**
- Implement synchronization service between web and Telegram systems
- Add registration source tracking to associate records
- Create unified API layer that serves both systems
- Implement conflict resolution for concurrent modifications
- Add monitoring and alerting for system health

---

## User Acceptance Testing Scenarios

### Scenario 1: Admin Creates Partner Associate (Web + Telegram)
1. Admin logs into web interface
2. Navigates to "Associate Management"
3. Clicks "Add Associate"
4. Fills form: alias="Partner A", role="Partner", status="Active"
5. Clicks "Save Associate"
6. System validates unique alias, creates associate record
7. Associate appears in list with "Partner A" role and "Web" registration source
8. Admin can now assign bookmakers to Partner A
9. Telegram bot recognizes new associate if needed for bet ingestion

**Expected Result**: New partner associate created successfully, available in both web and Telegram systems.

---

### Scenario 2: Partner Manages Own Bookmakers (Dual System)
1. Partner "Partner A" logs into web interface
2. Navigates to "Associate Management"
3. Sees their associate record with "Edit" and "Manage Bookmakers" options
4. Clicks "Manage Bookmakers"
5. Sees current bookmaker list, clicks "Add Bookmaker"
6. Adds "Pinnacle GBP" with details
7. Bookmaker appears in their list
8. Partner can edit/deactivate their own bookmakers
9. Changes synchronized to Telegram system if bookmaker has Telegram integration

**Expected Result**: Partner can self-manage bookmakers with changes reflected in both systems.

---

### Scenario 3: Admin Attempts to Edit Partner's Role
1. Admin "Admin" logs in, tries to edit Partner A's role to "Admin"
2. System shows error: "Only users with 'Admin' role can change role assignments"
3. Admin's action is logged in audit trail
4. Partner A's role remains unchanged
5. Change attempt blocked in both web and Telegram systems

**Expected Result**: Role-based access control enforced across both systems.

---

### Scenario 4: Telegram Registration During Web System Downtime
1. Web system experiences temporary downtime
2. Associate needs to register via Telegram for urgent bet placement
3. Telegram bot registers new associate successfully
4. When web system recovers, new associate data synchronized from Telegram to web
5. Associate appears in web system with "Telegram" registration source

**Expected Result**: Seamless fallback to Telegram system during web downtime.

---

## Technical Considerations

### Database Schema Changes

**New Tables Required:**
```sql
-- Admin users table
CREATE TABLE admin_users (
  admin_id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'admin',
  created_at_utc TEXT NOT NULL,
  last_login_utc TEXT,
  is_active INTEGER NOT NULL DEFAULT 1
);

-- Bookmaker assignments table
CREATE TABLE bookmaker_assignments (
  assignment_id INTEGER PRIMARY KEY AUTOINCREMENT,
  associate_id INTEGER NOT NULL REFERENCES associates(associate_id),
  bookmaker_id INTEGER NOT NULL REFERENCES bookmakers(bookmaker_id),
  assigned_at_utc TEXT NOT NULL,
  assigned_by_admin_id INTEGER REFERENCES admin_users(admin_id),
  status TEXT NOT NULL DEFAULT 'active',
  commission_rate DECIMAL(10,4),
  notes TEXT
);

-- Registration source tracking
ALTER TABLE associates ADD COLUMN registration_source TEXT DEFAULT 'web';
ALTER TABLE associates ADD COLUMN telegram_chat_id TEXT;
ALTER TABLE associates ADD COLUMN telegram_registered_at_utc TEXT;

-- Synchronization tracking
CREATE TABLE system_sync_log (
  sync_id INTEGER PRIMARY KEY AUTOINCREMENT,
  sync_type TEXT NOT NULL, -- 'web_to_telegram', 'telegram_to_web'
  source_record_id INTEGER NOT NULL,
  target_record_id INTEGER,
  sync_status TEXT NOT NULL, -- 'success', 'failed', 'conflict'
  sync_details TEXT,
  synced_at_utc TEXT NOT NULL,
  synced_by_admin_id INTEGER REFERENCES admin_users(admin_id)
);
```

### API Endpoints

**Associate Management API:**
- `GET /api/associates` - List all associates (admin only)
- `POST /api/associates` - Create new associate (admin only)
- `PUT /api/associates/{id}` - Update associate (role-based permissions)
- `DELETE /api/associates/{id}` - Delete associate (admin only)
- `GET /api/associates/{id}/bookmakers` - Get associate's bookmakers
- `POST /api/associates/{id}/bookmakers` - Assign bookmaker to associate
- `PUT /api/bookmaker-assignments/{id}` - Update assignment
- `DELETE /api/bookmaker-assignments/{id}` - Remove assignment

**Synchronization API:**
- `POST /api/sync/web-to-telegram` - Sync web changes to Telegram
- `POST /api/sync/telegram-to-web` - Sync Telegram changes to web
- `GET /api/sync/status` - Get synchronization status

### Security Considerations

**Authentication & Authorization:**
- JWT-based session management for web system
 
**Data Integrity for Event Admin:**
- Merges must be transactional: reassign bets/surebets first, then delete source event
- Prevent merges across different `sport` values by default
- Keep audit trail for merges, rebinding, and alias updates

**Observability:**
- Log admin actions to a structured audit stream
- Metrics for: alias reloads, pair‑key vs fuzzy matches, merges performed
- Role-based middleware for all API endpoints
- Maintain existing Telegram authentication system
- Password complexity requirements
- Secure session storage
- CSRF protection for state-changing operations

**Data Protection:**
- Input validation and sanitization
- SQL injection prevention
- Rate limiting on sensitive operations
- Audit logging for all data changes
- Synchronization conflict resolution

**Access Control:**
- Admin users: Full access to all associate operations
- Partner users: Limited to own associate record and bookmakers
- Permission checks before every operation
- Clear error messages for unauthorized attempts
- Cross-system permission validation

---

## Dependencies

### Upstream (Blockers)
- **Epic 0**: Foundation database schema and authentication patterns
- **Epic 1**: Bet ingestion associate selection integration points
- **Existing Telegram Bot**: Current Telegram system must remain functional

### Downstream (Consumers)
- **Epic 2**: Enhanced associate selection in bet review workflow
- **Epic 3**: Associate filtering in surebet matching dashboard
- **Epic 4**: Associate attribution in settlement calculations
- **Epic 5**: Associate-level reporting and reconciliation
- **Epic 6**: Associate management reports and analytics

---

## Definition of Done

Epic 7 is complete when ALL of the following are verified:

### Functional Validation
- [ ] All 4 stories (7.1-7.4) marked complete with passing acceptance criteria
- [ ] Web-based associate management fully functional
- [ ] Role-based access control working correctly
- [ ] Bookmaker assignment management operational
- [ ] Dual system integration working seamlessly
- [ ] Existing Telegram functionality preserved and enhanced
- [ ] Data synchronization between systems working correctly

### Technical Validation
- [ ] All new database tables created with proper constraints
- [ ] API endpoints implemented with authentication middleware
- [ ] Role-based permissions enforced consistently
- [ ] Synchronization service tested with conflict resolution
- [ ] No regression in existing Telegram registration functionality
- [ ] Both systems operational simultaneously

### User Testing
- [ ] All 4 UAT scenarios pass
- [ ] Admin can perform full associate lifecycle management in both systems
- [ ] Partner users can manage their own bookmakers only
- [ ] Role restrictions prevent unauthorized access in both systems
- [ ] Data synchronization works correctly between web and Telegram
- [ ] Fallback mechanisms function properly during system downtime

### Handoff Readiness
- [ ] Epic 2 team can use enhanced associate selection in bet review
- [ ] Epic 3 team can filter by associate in matching dashboard
- [ ] All downstream epics can reference associate management data
- [ ] Documentation updated for new administrative workflows
- [ ] Telegram bot integration maintained and enhanced

---

## Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Data synchronization conflicts | Medium | High | Implement conflict resolution; clear audit trail; test thoroughly |
| Dual system complexity | Medium | Medium | Clear separation of concerns; phased rollout; comprehensive testing |
| Role-based access complexity | Medium | High | Thorough testing of permission matrix; clear UI indicators |
| Telegram integration challenges | Low | Medium | Maintain existing Telegram functionality; test integration points |
| Performance with dual systems | Low | Medium | Implement caching; optimize synchronization; monitor performance |
| Security vulnerabilities in dual system | Low | High | Follow existing security patterns; regular security reviews; penetration testing |

---

## Success Metrics

### Completion Criteria
- All 4 stories delivered with passing acceptance criteria
- Epic 7 "Definition of Done" checklist 100% complete
- Zero blockers for Epics 2-6 (administrative dependencies resolved)
- Both web and Telegram systems operational and integrated

### Quality Metrics
- **Synchronization Success**: 95%+ of data changes synchronized within 5 minutes
- **Role Enforcement**: 0 unauthorized access attempts succeed in testing
- **UI Usability**: Admin tasks completable in <3 clicks, partner tasks in <5 clicks
- **System Availability**: 99.9% uptime for both systems during transition period
- **Telegram Compatibility**: 100% of existing Telegram functionality preserved

---

## Related Documents

- [PRD: Surebet Accounting System](../prd.md)
- [Epic 0: Foundation & Infrastructure](./epic-0-foundation.md)
- [Epic 1: Bet Ingestion Pipeline](./epic-1-bet-ingestion.md)
- [Epic 2: Bet Review & Approval](./epic-2-bet-review.md)
- [Epic 3: Surebet Matching & Safety](./epic-3-surebet-matching.md)
- [Implementation Roadmap](./implementation-roadmap.md)

---

## Notes

### Why Dual System Approach Matters

This epic provides **enhanced administration** while maintaining system reliability:

1. **Preserves Investment**: Existing Telegram system remains functional
2. **Reduces Risk**: No hard cutoff of existing system during transition
3. **Enables Gradual Migration**: Users can adapt at their own pace
4. **Provides Fallback**: Telegram available if web system has issues
5. **Maintains Operations**: Both systems can work simultaneously during transition

### Integration Strategy

**Phase 1**: Deploy web interface alongside Telegram (dual operation)
**Phase 2**: Implement data synchronization between systems
**Phase 3**: Gradual migration of users from Telegram to web
**Phase 4**: Optional phase-out of Telegram when web system is fully adopted

### Future Extensibility

The dual-system approach provides foundation for:
- Advanced user analytics and reporting across both systems
- Enhanced permission systems with cross-system validation
- Integration with external identity providers
- Automated associate onboarding workflows
- Multi-channel communication (web + Telegram + future channels)

---

**End of Epic**
### Story 7.5: Event Catalog & Normalization Admin

**As a system administrator**, I want to manage canonical events, aliases, and resolve duplicates so that event normalization is consistent and matching is reliable without per‑bet edits.

**Acceptance Criteria:**
- [ ] Canonical Events page (id, name, sport, kickoff, team1_slug, team2_slug, pair_key, created)
- [ ] Search by name; filter by sport/date
- [ ] Merge events flow (source → target): preview affected bets/surebets; transactional reassign; delete source; audit log
- [ ] Recompute pair key updates team slugs + pair_key from normalized name
- [ ] Suggestions panel: show top rebinding candidates (pair key / strict fuzzy ≥90) and allow one‑click rebind (audit)
- [ ] Aliases editor for `data/team_aliases.json` with validation and live reload
- [ ] All actions write audit entries with actor and timestamp

**Technical Notes:** use `EventNormalizer` for normalization and pair key computation; enforce sport compatibility on merges.

### Story 7.6: Maintenance & Dev Tools

**As a developer/operator**, I want fast reset and validation tools so I can test cleanly and keep the system healthy.

**Acceptance Criteria:**
- [ ] DB reset script (dev): `python scripts/reset_dev_db.py [--hard] [--yes]` (recreate schema + seeds; optional data purge)
- [ ] Rebuild indexes & validate schema command in admin page
- [ ] Backfill to compute team slugs/pair_key for legacy canonical events
- [ ] Health checks: DB connectivity, schema validation, alias load status, OpenAI key presence
- [ ] All tools log actions with operator identity
**Event Admin API:**
- `GET /api/events` - List canonical events (filters: sport, date, q)
- `POST /api/events/{id}/recompute-pair-key` - Recompute team slugs/pair key
- `POST /api/events/merge` - Merge two canonical events (source → target)
- `POST /api/aliases` - Update team aliases document
- `POST /api/aliases/reload` - Reload aliases at runtime

**Maintenance API (admin):**
- `POST /api/maintenance/reset-db` (dev only) - Trigger reset or provide instructions
- `POST /api/maintenance/rebuild-indexes` - Rebuild DB indexes
- `POST /api/maintenance/backfill-pair-keys` - Compute slugs/pair_key for legacy rows
