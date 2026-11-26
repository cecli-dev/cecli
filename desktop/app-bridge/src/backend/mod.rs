//! In-process backends used by tests and protocol conformance checks.

pub mod fake;

pub use fake::{FakeBackend, FakeState};
