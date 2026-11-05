# Evidence envelope and local object retention

`Build` validates the frozen v1 envelope and returns exact canonical JSON bytes
and their Keccak-256 hash. `Parse` accepts only those exact bytes. Both service
classes use their specified details shape; a class/details mismatch fails.
Unknown and duplicate members, alternative escapes, whitespace and trailing
content fail rather than silently changing the disclosed commitment. The
normative predicate vector fixes the expected hash.

The closed schema uses ASCII strings, fixed integers 1 and 2, and sorted object
keys, which form a subset of RFC 8785 supported by Go's JSON encoder. This is not
a general JCS library. Hex spelling is retained. Schema-valid zero hashes are
accepted; a caller must still authenticate the purchase, seller receipt, input
objects, assignment and predicate semantics. Encoding alone proves none of them.
The local 1 MiB envelope parsing bound is an implementation resource limit;
callers must also apply their profile's smaller evidence publication limit.

`NewStore(dir, maxBytes)` creates one directory under an existing parent, then
syncs it and the parent. `Put` stores arbitrary exact bytes, permitting evidence
and referenced source or comparison objects to share one content-addressed store.
Canonical validation is explicit through `Build`/`Parse`, not implicit in `Put`.
Filenames are the 64 lowercase hexadecimal digits of the typed bytes32 digest.
Writes use a temporary file, file fsync, atomic no-overwrite hard link, temporary
unlink and directory fsync. A retry verifies existing bytes and syncs the
directory, preserving its inode. Errors after publication can mean the object
already exists; retrying the same bytes is safe. Concurrent writers are supported.

`Get` rejects symlinks and nonregular files, bounds the read, and recomputes the
hash before returning bytes. Final object files are mode 0444; this is an API
immutability guarantee with corruption detection, not protection against the OS
owner changing files. The directory and its ancestors must remain under trusted
operator control. The implementation requires local Unix hard links and fsync;
it does not establish remote filesystem guarantees or survive arbitrary storage
hardware failure. Process interruption can leave harmless `.pending-*` files;
there is no cleanup or object deletion API.

Tests cover the normative vector, both classes, strict parsing and shape errors,
reopen/repeat retention, concurrent writers, tamper rejection, missing objects,
size limits and symlinks. Reopen tests exercise durable syscall completion but
are not a hardware power-loss experiment. This component does not poll a chain,
sign or submit verdicts, serve disclosure transactions, or enforce a retention
scheduler.
