package starter

import (
	"reflect"
	"testing"
)

// The provided tests are deliberately thin. Add your own edge cases below.
func TestProvided(t *testing.T) {
	roles := []Role{
		{Name: "viewer", Permissions: []string{"inventory:read"}},
		{Name: "editor", Permissions: []string{"inventory:write"}, Inherits: []string{"viewer"}},
	}
	u := User{ID: "u1", Roles: []string{"editor"}}

	got, err := AllPermissions(u, roles)
	if err != nil {
		t.Fatal(err)
	}
	if want := []string{"inventory:read", "inventory:write"}; !reflect.DeepEqual(got, want) {
		t.Fatalf("got %v want %v", got, want)
	}
	if ok, _ := HasPermission(u, roles, "inventory:write"); !ok {
		t.Fatal("expected inventory:write")
	}
}

// TODO: unknown role, no roles, duplicates, cycle, diamond, empty permission...
