/* Minimal stdarg.h so libclang can parse xv6 without compiler resource headers.
   (The real build gets this file from the RISC-V GCC installation.) */
#ifndef XV6X_STDARG_H
#define XV6X_STDARG_H
typedef __builtin_va_list va_list;
#define va_start(ap, last) __builtin_va_start(ap, last)
#define va_arg(ap, type) __builtin_va_arg(ap, type)
#define va_end(ap) __builtin_va_end(ap)
#define va_copy(d, s) __builtin_va_copy(d, s)
#endif
