# New Employee Login Provisioning

When HR creates a new employee, GoobyDesk now writes both records:

1. The HR profile goes into `HrStore`.
2. The auth record goes into `EmployeeStore`.
3. The profile page shows the temporary password once.

## Flow

`new_employee()` reads the form, builds the HR record with `_build_employee_record()`, then calls `_provision_employee_login_access()` when login access is enabled.

That helper uses:

- `_derive_auth_username()` to pick a unique username.
- `_map_hr_role_to_auth_payload()` to convert the HR role into login roles.
- `_build_employee_auth_record()` to build the auth payload.

If auth save fails, the HR record is rolled back.

## Variables

- `employee_id`: the default login username.
- `auth_username_override`: optional username from the form.
- `create_login_access`: checkbox value that turns provisioning on or off.
- `temporary_password`: one-time password shown after creation.
- `provisioning_status`: HR access state, such as `pending`, `complete`, or `disabled`.
- `login_enabled`: flag stored in the HR access block.

## Functions

- `new_employee()`: handles the create request.
- `_build_employee_record()`: builds the HR employee object.
- `_build_employee_access()`: builds the HR access block.
- `_provision_employee_login_access()`: creates the auth record and password.
- `_build_employee_auth_record()`: stores auth fields like `tech_username`, `roles`, and `password_hash`.

## Notes

- The auth username must be 3-32 characters.
- Allowed characters are letters, digits, `_`, and `-`.
- The login page accepts the new auth record using `tech_username`.
