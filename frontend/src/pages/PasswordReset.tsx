// Shim sobre libra-ui/PasswordReset (mismo patrón que Login/Usuarios).
// Las dos pantallas son públicas: van fuera de ProtectedRoute en App.tsx,
// porque quien las usa justamente no puede entrar.
import { createForgotPassword, createResetPassword } from 'libra-ui/PasswordReset'

const branding = { productName: 'MedLibra', productInitial: 'M' }

// El forgot-password lleva el mismo captcha que el login (captcha=True en
// app/routers/auth.py): sin él, el endpoint manda correos a pedido de
// cualquiera. El reset-password no lo lleva: ya exige el token del correo.
export const ForgotPassword = createForgotPassword({ ...branding, captchaPath: '/auth/captcha' })
export const ResetPassword = createResetPassword(branding)
