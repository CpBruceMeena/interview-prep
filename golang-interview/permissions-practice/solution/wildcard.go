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
