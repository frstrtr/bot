# Refactor: Anti-Spam Bot as Message Router + Firewall

## Concept

The anti-spam bot functions like a network firewall with routing capabilities:
- **Messages** = Network packets
- **Rules** = Firewall rules (ordered, priority-based)
- **Actions** = PASS, DROP, ROUTE, BAN
- **Threads** = Routing destinations (SUSPICIOUS, AUTOREPORT, AUTOBAN, etc.)
- **User Trust Levels** = Network zones (ESTABLISHED, MONITORED, REGULAR, BANNED)

## Current Architecture (Scattered)

```
┌─────────────────────────────────────────────────────────────────┐
│                         main.py                                  │
│  - Multiple nested if/elif blocks                               │
│  - Rules scattered across 13,000+ lines                         │
│  - Hard to see full rule chain at a glance                      │
│  - Duplicate code for routing/reporting                         │
└─────────────────────────────────────────────────────────────────┘
```

## Proposed Architecture

### Message Flow Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                      INCOMING MESSAGE                           │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  RULE 1: Source Check (777000 = Anonymous Admin)                │
│  Action: PASS (skip all checks)                                 │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  RULE 2: Sender in banned_users_dict?                           │
│  Action: DROP + ROUTE to ADMIN_AUTOBAN                          │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  RULE 3: Forward from unknown source?                           │
│  ├─ User ESTABLISHED → ROUTE to SUSPICIOUS (keep msg)           │
│  ├─ User MONITORED   → DROP + ROUTE to AUTOREPORT               │
│  └─ User REGULAR     → DROP + ROUTE to SUSPICIOUS               │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  RULE 4: LOLS/CAS/P2P flagged?                                  │
│  Action: DROP + BAN + ROUTE to ADMIN_AUTOBAN                    │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  RULE 5: Spam patterns (emojis, caps, sentences)?               │
│  Action: DROP + ROUTE to AUTOREPORT                             │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  RULE 6: New user (<10 sec) with spam triggers?                 │
│  Action: DROP + BAN + ROUTE to AUTOBAN                          │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
                           PASS
```

### Data Structures

```python
from dataclasses import dataclass
from typing import Callable, Literal, Optional, List
from enum import Enum

class Action(Enum):
    PASS = "pass"           # Allow message through
    DROP = "drop"           # Delete message
    ROUTE = "route"         # Forward to admin thread
    BAN = "ban"             # Ban user from all chats
    MONITOR = "monitor"     # Add to active_user_checks

class UserTrust(Enum):
    ESTABLISHED = "established"   # ≥10 msgs, ≥90 days old
    MONITORED = "monitored"       # In active_user_checks_dict
    REGULAR = "regular"           # Normal user
    BANNED = "banned"             # In banned_users_dict
    SYSTEM = "system"             # 777000, 136817688, etc.

class RouteTarget(Enum):
    SUSPICIOUS = "ADMIN_SUSPICIOUS"
    AUTOREPORT = "ADMIN_AUTOREPORTS"
    AUTOBAN = "ADMIN_AUTOBAN"
    MANBAN = "ADMIN_MANBAN"
    TECHNOLOG = "TECHNO_LOGGING"

@dataclass
class FirewallRule:
    """A single firewall rule for message processing."""
    name: str
    description: str
    priority: int  # Lower = earlier in chain
    
    # Condition
    condition: Callable[["MessageContext"], bool]
    
    # Actions
    actions: List[Action]
    route_to: Optional[RouteTarget] = None
    
    # Modifiers based on user trust
    trust_overrides: Optional[dict[UserTrust, List[Action]]] = None
    
    # Whether to stop processing after this rule matches
    terminal: bool = True

@dataclass
class MessageContext:
    """Context object passed through the rule chain."""
    message: Message
    user_id: int
    user_trust: UserTrust
    
    # Cached checks (lazy-loaded)
    _spam_check_result: Optional[bool] = None
    _is_forward: Optional[bool] = None
    _has_spam_entities: Optional[bool] = None
    
    @property
    def spam_check(self) -> bool:
        if self._spam_check_result is None:
            self._spam_check_result = await spam_check(self.user_id)
        return self._spam_check_result
```

### Rule Definitions (rules.py)

```python
FIREWALL_RULES = [
    # Priority 0: System accounts - always pass
    FirewallRule(
        name="system_accounts",
        description="Allow system accounts (anonymous admin, channel bot)",
        priority=0,
        condition=lambda ctx: ctx.user_id in [777000, 136817688],
        actions=[Action.PASS],
        terminal=True,
    ),
    
    # Priority 10: Already banned users
    FirewallRule(
        name="banned_users",
        description="Block messages from banned users",
        priority=10,
        condition=lambda ctx: ctx.user_trust == UserTrust.BANNED,
        actions=[Action.DROP, Action.ROUTE],
        route_to=RouteTarget.AUTOBAN,
        terminal=True,
    ),
    
    # Priority 20: Forward from unknown source
    FirewallRule(
        name="forward_unknown_source",
        description="Handle forwards from unknown channels/users",
        priority=20,
        condition=lambda ctx: ctx.is_forward_from_unknown,
        actions=[Action.DROP, Action.ROUTE],
        route_to=RouteTarget.SUSPICIOUS,
        trust_overrides={
            UserTrust.ESTABLISHED: [Action.ROUTE],  # No DROP for established
            UserTrust.MONITORED: [Action.DROP, Action.ROUTE],  # AUTOREPORT instead
        },
        terminal=True,
    ),
    
    # Priority 30: LOLS/CAS/P2P flagged
    FirewallRule(
        name="external_spam_list",
        description="Ban users flagged by LOLS/CAS/P2P",
        priority=30,
        condition=lambda ctx: ctx.spam_check is True,
        actions=[Action.DROP, Action.BAN, Action.ROUTE],
        route_to=RouteTarget.AUTOBAN,
        terminal=True,
    ),
    
    # ... more rules
]
```

### Rule Engine (engine.py)

```python
class FirewallEngine:
    def __init__(self, rules: List[FirewallRule]):
        self.rules = sorted(rules, key=lambda r: r.priority)
    
    async def process(self, message: Message) -> ProcessResult:
        ctx = await self._build_context(message)
        
        for rule in self.rules:
            if rule.condition(ctx):
                actions = self._get_actions(rule, ctx.user_trust)
                result = await self._execute_actions(ctx, actions, rule)
                
                if rule.terminal:
                    return result
        
        return ProcessResult(action=Action.PASS)
    
    def _get_actions(self, rule: FirewallRule, trust: UserTrust) -> List[Action]:
        if rule.trust_overrides and trust in rule.trust_overrides:
            return rule.trust_overrides[trust]
        return rule.actions
    
    async def _execute_actions(self, ctx: MessageContext, actions: List[Action], rule: FirewallRule):
        for action in actions:
            if action == Action.DROP:
                await self._delete_message(ctx)
            elif action == Action.BAN:
                await self._ban_user(ctx)
            elif action == Action.ROUTE:
                await self._route_to_admin(ctx, rule.route_to)
            elif action == Action.MONITOR:
                await self._add_to_monitoring(ctx)
```

## Benefits

1. **Clarity**: All rules visible in one place
2. **Maintainability**: Add/modify rules without touching main logic
3. **Testability**: Rules can be unit tested independently
4. **Configurability**: Rules could be loaded from config file
5. **Debugging**: Easy to log which rule matched and why
6. **Consistency**: Uniform handling of actions (routing, deleting, etc.)

## Migration Path

1. **Phase 1**: Create `rules.py` and `engine.py` alongside existing code
2. **Phase 2**: Implement rule definitions matching current behavior
3. **Phase 3**: Add logging to compare old vs new decisions
4. **Phase 4**: Gradually switch handlers to use engine
5. **Phase 5**: Remove old scattered if/elif blocks

## Considerations

- **Performance**: Lazy evaluation of expensive checks (LOLS/CAS/P2P)
- **Async**: Rules may need async condition checks
- **State**: Some rules depend on runtime state (active_user_checks_dict)
- **Backward Compatibility**: Must match current behavior exactly first

## Related Ideas

- **Rule versioning**: Track which rule version made each decision
- **A/B testing**: Run multiple rule sets, compare outcomes
- **Admin UI**: Web interface to view/modify rules
- **Metrics**: Track rule hit rates, false positives

---

Created: 2025-12-05
Branch: refactor/firewall-model
Status: IDEA - To be implemented after production stabilization
