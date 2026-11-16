// The sign-in form's two steps, as in the approved mock: the email first ("Continue with email"), then
// the password ("Sign in"). Both steps are in the browser only; the server gets one submit.

export type Step = 'email' | 'password'

export type Decision =
  | { kind: 'next' } // show the password field
  | { kind: 'submit' } // post email and password to the login action
  | { kind: 'error'; field: 'email' | 'password'; message: string }

const EMAIL = /^[^@\s]+@[^@\s]+\.[^@\s]+$/

/** What a press of the button (or Enter) does at this step with these values. */
export function decide(step: Step, email: string, password: string): Decision {
  if (!EMAIL.test(email.trim())) return { kind: 'error', field: 'email', message: 'Enter the email your admin gave you.' }
  if (step === 'email') return { kind: 'next' }
  if (!password) return { kind: 'error', field: 'password', message: 'Enter your password.' }
  return { kind: 'submit' }
}

/** The button's label at each step. */
export const buttonLabel = (step: Step) => (step === 'email' ? 'Continue with email' : 'Sign in')
