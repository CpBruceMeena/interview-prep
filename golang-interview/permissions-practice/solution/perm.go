package solution

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
	for _, p := range role.Permissifons {
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
