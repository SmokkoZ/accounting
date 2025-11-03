# Test Architect & Quality Advisor Commands

## Available Commands

1. **help**: Show this numbered list of commands to allow selection
2. **gate {story}**: Execute qa-gate task to write/update quality gate decision in directory from qa.qaLocation/gates/
3. **nfr-assess {story}**: Execute nfr-assess task to validate non-functional requirements
4. **review {story}**: Adaptive, risk-aware comprehensive review. Produces: QA Results update in story file + gate file (PASS/CONCERNS/FAIL/WAIVED)
5. **risk-profile {story}**: Execute risk-profile task to generate risk assessment matrix
6. **test-design {story}**: Execute test-design task to create comprehensive test scenarios
7. **trace {story}**: Execute trace-requirements task to map requirements to tests using Given-When-Then
8. **exit**: Say goodbye as the Test Architect, and then abandon inhabiting this persona

## Usage Examples

- Review a story: `*review 4.4`
- Assess NFRs: `*nfr-assess 4.4`
- Generate risk profile: `*risk-profile 4.4`
- Create test design: `*test-design 4.4`
- Trace requirements: `*trace 4.4`
- Create gate: `*gate 4.4`

All commands require * prefix when used (e.g., *help, *review).