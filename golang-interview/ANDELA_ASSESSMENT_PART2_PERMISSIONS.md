# 🔐 Practice Round: Permissions System (Online Assessment, Part 2)

> **What this is:** a practice version of "Part 2: Real-World Programming, Business Data Structures & Algorithms [Intermediate]" from the Andela / Woven online assessment for a senior Go (inventory services) role.
> **Not the real test.** It is rebuilt from the public description only: users, roles and permissions; compute all permissions for a user; check one permission; scored on correctness, edge cases, reuse, extra tests, and clean code. The real task may use different names, language scaffolding or data shapes.

---

## 1. What the task probably looks like

You get a small starter repo (often with a few failing or missing functions and a couple of existing tests) and roughly 25 to 35 minutes of the 40 to 60 minute assessment for this part. Expect something close to:

```text
type Role struct { Name string; Permissions []string }
type User struct { ID string; Roles []string }

// TODO: all permissions the user has
func AllPermissions(u User, roles []Role) []string

// TODO: does the user have this permission?
func HasPermission(u User, roles []Role, perm string) bool
```

The data is business-flavoured: `inventory:read`, `inventory:write`, `orders:cancel`, roles like `warehouse-picker`, `store-manager`, `admin`.

## 2. How it is scored (from the description)

| Criterion | What earns the points |
|---|---|
| **Correctness** | Both functions return the right answer on the given examples. |
| **Edge cases** | Empty inputs, duplicates, unknown roles, inheritance and cycles, empty permission string. |
| **No duplicated logic** | `HasPermission` reuses `AllPermissions` (or a shared helper). Do not write the traversal twice. |
| **Your own tests** | Add table-driven tests beyond the provided ones, especially for edge cases. |
| **Clean code** | Small helpers, descriptive names, comments that explain *why*, not *what*. |

## 3. Approach: 5 steps, in this order

1. **Read the starter code and existing tests first** (2 to 3 min). Note the data shapes, whether roles are looked up by name, and whether the existing tests show the expected output order.
2. **List edge cases before coding**, and write them as test names. Decide each answer deliberately:
   - user with no roles; role with no permissions;
   - same permission granted by several roles (dedupe);
   - user lists the same role twice;
   - role name not found: return an error, skip it, or treat as no permissions? **Pick one, state it in a comment, test it.** If the spec says nothing, an error is safest, but follow the starter tests if they imply otherwise.
   - role inheritance, diamonds and cycles (only if roles can reference other roles).
3. **Write one traversal helper** that collects permissions into a set. Build `AllPermissions` on it, then `HasPermission` on `AllPermissions`.
4. **Return a deterministic order** (sorted) so tests compare cleanly. Maps iterate randomly in Go.
5. **Add tests, then read your own diff** for naming and comments. Leave 3 to 5 minutes for this.

## 4. Reference solution (Go)

Passes `go vet` and `go test -race`, and is in [`solution/perm.go`](permissions-practice/solution/perm.go) (package `solution`; shown here as `perm`). It supports role inheritance because that is the most likely twist; if your version of the task has flat roles, delete the `Inherits` handling and the code gets shorter.

```go
package perm

import (
	"errors"
	"fmt"
	"sort"
)

// Role grants permissions directly and may inherit from other roles.
type Role struct {
	Name        string
	Permissions []string
	Inherits    []string // names of parent roles
}

// User holds role names; unknown names are reported, not ignored.
type User struct {
	ID    string
	Roles []string
}

var ErrUnknownRole = errors.New("unknown role")

// Directory is the lookup the functions work against.
type Directory struct {
	roles map[string]Role
}

func NewDirectory(roles []Role) *Directory {
	d := &Directory{roles: make(map[string]Role, len(roles))}
	for _, r := range roles {
		d.roles[r.Name] = r
	}
	return d
}

// collect walks one role and its ancestors, adding permissions to out.
// visited makes diamond inheritance cheap and stops cycles from looping forever.
func (d *Directory) collect(name string, visited map[string]bool, out map[string]struct{}) error {
	if visited[name] {
		return nil
	}
	visited[name] = true
	role, ok := d.roles[name]
	if !ok {
		return fmt.Errorf("%w: %q", ErrUnknownRole, name)
	}
	for _, p := range role.Permissions {
		out[p] = struct{}{}
	}
	for _, parent := range role.Inherits {
		if err := d.collect(parent, visited, out); err != nil {
			return err
		}
	}
	return nil
}

// AllPermissions returns the user's deduplicated, sorted permissions.
func (d *Directory) AllPermissions(u User) ([]string, error) {
	set := map[string]struct{}{}
	visited := map[string]bool{}
	for _, name := range u.Roles {
		if err := d.collect(name, visited, set); err != nil {
			return nil, err
		}
	}
	perms := make([]string, 0, len(set))
	for p := range set {
		perms = append(perms, p)
	}
	sort.Strings(perms)
	return perms, nil
}

// HasPermission reports whether the user holds the permission.
func (d *Directory) HasPermission(u User, perm string) (bool, error) {
	perms, err := d.AllPermissions(u)
	if err != nil {
		return false, err
	}
	i := sort.SearchStrings(perms, perm)
	return i < len(perms) && perms[i] == perm, nil
}
```

**Why this shape**

- One helper (`collect`) owns the traversal. Both public functions are thin.
- A `visited` set handles diamonds (admin to editor and billing, both reaching viewer) and cycles in one line.
- A map-backed `Directory` makes role lookup O(1) instead of scanning a slice per user role.
- Sorting at the end gives stable output; `HasPermission` then uses binary search.
- `errors.Is`-friendly sentinel error, so callers can tell "bad data" from "no permission".

**Complexity:** roughly O(R + E + P log P) per user for R roles visited, E inheritance edges, P distinct permissions (the log term is the sort).

## 5. Tests

```go
package perm

import (
	"errors"
	"reflect"
	"testing"
)

func testDir() *Directory {
	return NewDirectory([]Role{
		{Name: "viewer", Permissions: []string{"read"}},
		{Name: "editor", Permissions: []string{"write", "read"}, Inherits: []string{"viewer"}},
		{Name: "admin", Permissions: []string{"delete"}, Inherits: []string{"editor", "billing"}},
		{Name: "billing", Permissions: []string{"invoice", "read"}},
		{Name: "loop-a", Permissions: []string{"a"}, Inherits: []string{"loop-b"}},
		{Name: "loop-b", Permissions: []string{"b"}, Inherits: []string{"loop-a"}},
		{Name: "empty"},
	})
}

func TestAllPermissions(t *testing.T) {
	d := testDir()
	tests := []struct {
		name  string
		roles []string
		want  []string
	}{
		{"no roles", nil, []string{}},
		{"role without permissions", []string{"empty"}, []string{}},
		{"single role", []string{"viewer"}, []string{"read"}},
		{"inherited and deduplicated", []string{"editor"}, []string{"read", "write"}},
		{"diamond inheritance", []string{"admin"}, []string{"delete", "invoice", "read", "write"}},
		{"duplicate roles", []string{"viewer", "viewer"}, []string{"read"}},
		{"cycle terminates", []string{"loop-a"}, []string{"a", "b"}},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			got, err := d.AllPermissions(User{ID: "u", Roles: tc.roles})
			if err != nil {
				t.Fatal(err)
			}
			if !reflect.DeepEqual(got, tc.want) {
				t.Fatalf("got %v want %v", got, tc.want)
			}
		})
	}
}

func TestUnknownRole(t *testing.T) {
	d := testDir()
	if _, err := d.AllPermissions(User{Roles: []string{"ghost"}}); !errors.Is(err, ErrUnknownRole) {
		t.Fatalf("want ErrUnknownRole, got %v", err)
	}
}

func TestHasPermission(t *testing.T) {
	d := testDir()
	u := User{Roles: []string{"editor"}}
	for perm, want := range map[string]bool{"read": true, "write": true, "delete": false, "": false} {
		got, err := d.HasPermission(u, perm)
		if err != nil || got != want {
			t.Fatalf("%q: got %v,%v want %v", perm, got, err, want)
		}
	}
}
```

Notice what is covered: empty cases, dedupe, diamond, duplicate role names, a cycle, an unknown role, and the empty permission string. These are the cases a reviewer scans for.

## 6. Go-specific things this round rewards

| Area | What to do in Go |
|---|---|
| **Errors** | Sentinel error plus `fmt.Errorf("%w: %q", ErrUnknownRole, name)`; test with `errors.Is`. Do not `panic` on bad data and do not compare error strings. |
| **Sets** | `map[string]struct{}` for dedupe. Convert to a sorted slice at the boundary with `sort.Strings` (or `slices.Sort`). |
| **Nil vs empty slice** | Return `[]string{}` (not `nil`) for "no permissions" if tests use `reflect.DeepEqual`: `nil` and empty are **not** equal there. Decide once and test it. |
| **Don't mutate inputs** | Never sort or append to `role.Permissions` in place; it aliases the caller's array. |
| **Receiver design** | A small `Directory` built once (map lookup) beats scanning a `[]Role` for every user role. Constructor `NewDirectory`, read-only afterwards, so safe to share between goroutines. |
| **Table-driven tests** | `tests := []struct{name string; ...}` plus `t.Run(tc.name, ...)`. One case per edge case, descriptive names. Use `t.Helper()` in any assertion helper. |
| **Tooling** | Run `gofmt -l .`, `go vet ./...`, `go test -race -count=1 ./...` before finishing. Graders notice formatting. |
| **Stdlib first** | `strings.CutPrefix` / `CutSuffix`, `slices`, `sort.SearchStrings`. No third-party packages. |
| **Comments** | Doc comment on every exported name starting with the name; inline comments record decisions (unknown role = error, deny wins). |

### Wildcards and deny rules (the most likely twist)

Kept in a separate file so the core solution stays small. Verified with `go test -race`.

```go
package solution

import "strings"

// Permissions starting with "!" are denials; a matching denial always wins.
// "*" matches everything and "ns:*" matches every permission in that namespace.

func matches(granted, requested string) bool {
	if granted == "*" || granted == requested {
		return true
	}
	ns, ok := strings.CutSuffix(granted, ":*")
	return ok && strings.HasPrefix(requested, ns+":")
}

// HasPermissionWithRules is HasPermission with wildcard and deny support.
func (d *Directory) HasPermissionWithRules(u User, requested string) (bool, error) {
	perms, err := d.AllPermissions(u)
	if err != nil {
		return false, err
	}
	allowed := false
	for _, p := range perms {
		if denied, ok := strings.CutPrefix(p, "!"); ok {
			if matches(denied, requested) {
				return false, nil // deny wins, stop early
			}
			continue
		}
		allowed = allowed || matches(p, requested)
	}
	return allowed, nil
}
```

```go
package solution

import "testing"

func TestHasPermissionWithRules(t *testing.T) {
	d := NewDirectory([]Role{
		{Name: "ops", Permissions: []string{"orders:*", "inventory:read"}},
		{Name: "no-cancel", Permissions: []string{"!orders:cancel"}},
		{Name: "root", Permissions: []string{"*"}},
	})
	tests := []struct {
		name  string
		roles []string
		perm  string
		want  bool
	}{
		{"namespace wildcard", []string{"ops"}, "orders:create", true},
		{"other namespace", []string{"ops"}, "billing:read", false},
		{"exact grant", []string{"ops"}, "inventory:read", true},
		{"prefix is not a match", []string{"ops"}, "orders", false},
		{"deny beats wildcard", []string{"ops", "no-cancel"}, "orders:cancel", false},
		{"deny is specific", []string{"ops", "no-cancel"}, "orders:create", true},
		{"global wildcard", []string{"root"}, "anything:at-all", true},
		{"deny beats global wildcard", []string{"root", "no-cancel"}, "orders:cancel", false},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			got, err := d.HasPermissionWithRules(User{Roles: tc.roles}, tc.perm)
			if err != nil || got != tc.want {
				t.Fatalf("got %v,%v want %v", got, err, tc.want)
			}
		})
	}
}
```

## 7. Other twists, and how to handle them

| Twist | Change |
|---|---|
| **Wildcards** (`orders:*`, `*`) | In `HasPermission`, also accept a held permission `ns:*` when the requested one starts with `ns:`. Keep `AllPermissions` returning the raw grants. |
| **Deny rules** (`!orders:cancel`) | Collect allows and denies separately; a deny wins. State that rule in a comment. |
| **Direct user permissions** | Add `User.Permissions`, seed the set with them before walking roles. |
| **Case or whitespace** | Normalise once in one helper, not at every call site. |
| **Many users, same roles** | Cache each role's resolved permission set (memoise per role), then union per user. |
| **Concurrency** | Directory is read-only after construction, so it is safe to share. Mention a `sync.RWMutex` or copy-on-write only if roles can change at runtime. |
| **Output as a set** | Return `map[string]struct{}` instead of a slice if the starter asks for it. Keep the sort only where order matters. |

## 8. Common mistakes that cost points

- Copy-pasting the traversal into `HasPermission` instead of reusing it.
- Returning in map order, so tests flake.
- Silently ignoring an unknown role without saying so in a comment or test.
- Infinite recursion on a cyclic role graph.
- Mutating the caller's slices (for example sorting `role.Permissions` in place).
- No tests of your own. The task explicitly rewards them.
- Comments that restate the code (`// loop over roles`) instead of recording decisions.

## 9. Practice drill (runnable)

Everything is in `permissions-practice/`:

| Path | Purpose |
|---|---|
| [`starter/perm.go`](permissions-practice/starter/perm.go) | Stub functions, the way a starter repo would hand them to you |
| [`starter/perm_test.go`](permissions-practice/starter/perm_test.go) | A thin "provided" test; add your own cases here |
| [`solution/`](permissions-practice/solution/perm.go) | Reference solution, tests, and the wildcard/deny extension |

```bash
cd golang-interview/permissions-practice
go test ./starter/                     # fails until you implement it
go test -race -count=1 ./solution/     # reference passes
```

1. Set a 25-minute timer and implement `starter/` **without opening `solution/`**. Add at least six edge-case tests.
2. Compare with the reference, and fix anything you missed.
3. Repeat with a twist: add wildcards and deny rules, then caching per role.
4. Finish with `gofmt -l . && go vet ./... && go test -race ./...`.

---

*Related prep: [Go Concurrency Coding Challenges](CONCURRENCY_CODING_CHALLENGES.md), [Go Interview Questions](INTERVIEW_QUESTIONS.md), [LLD Interview Playbook](../python-low-level-design/LLD_INTERVIEW_PLAYBOOK.md).*
