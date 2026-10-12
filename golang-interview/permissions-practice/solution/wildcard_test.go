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
