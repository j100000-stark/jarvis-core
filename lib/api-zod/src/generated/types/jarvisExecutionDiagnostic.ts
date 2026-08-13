/**
 * Structured diagnostic detail for a failed goal execution.
 * Present on JarvisMessageResponse when success=false and an exception was
 * caught by the assistant (as opposed to a clean step-level tool failure
 * which is reported via executionSteps and failure).
 *
 * All string fields are sanitized server-side — no secrets, keys, or tokens.
 */
export interface JarvisExecutionDiagnostic {
  /** Machine-readable error code (e.g. BRAIN_UNAVAILABLE, EXECUTION_ERROR). */
  code: string;
  /** Python exception class name (e.g. BrainUnavailableError, ValueError). */
  type: string;
  /** Human-readable, sanitized error description. */
  message: string;
  /** Which subsystem raised the error (assistant / planner / brain / executor). */
  component: string;
  /** Failing plan step identifier if known; null otherwise. */
  step: string | null;
  /** Whether a retry or configuration change is likely to resolve the failure. */
  recoverable: boolean;
  /** Sequential incident counter for this JARVIS session. */
  incidentId: number;
  /** Internal operation label — safe to display (no sensitive data). */
  operation: string;
  /** ISO-8601 timestamp when the incident was recorded. */
  timestamp: string;
}
