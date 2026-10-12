package starter

// Role grants permissions directly and may inherit from other roles.
type Role struct {
	Name        string
	Permissions []string
	Inherits    []string
}

type User struct {
	ID    string
	Roles []string
}

// AllPermissions returns every permission the user holds, deduplicated and sorted.
// TODO: implement.
func AllPermissions(u User, roles []Role) ([]string, error) {
	return nil, nil
}

// HasPermission reports whether the user holds perm.
// TODO: implement, reusing AllPermissions.
func HasPermission(u User, roles []Role, perm string) (bool, error) {
	return false, nil
}
