package solution

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
