"use client";

import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { post, ApiError } from "@/lib/api";

const schema = z.object({
  email: z.string().email("Ingresa un correo válido"),
});

type FormValues = z.infer<typeof schema>;

export default function LoginPage() {
  const [enviado, setEnviado] = useState(false);

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
    setError,
  } = useForm<FormValues>({ resolver: zodResolver(schema) });

  async function onSubmit(values: FormValues) {
    try {
      await post("/auth/magic-link", values);
      setEnviado(true);
    } catch (err) {
      const detalle = err instanceof ApiError ? err.detalle : "No se pudo enviar el link";
      setError("email", { message: detalle });
    }
  }

  return (
    <div className="flex min-h-svh flex-col items-center justify-center gap-6 p-4">
      <p className="text-2xl font-semibold tracking-tight">instagod</p>
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle>Iniciar sesión</CardTitle>
          <CardDescription>
            Sin contraseñas: te enviamos un link de acceso a tu correo.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {enviado ? (
            <div className="space-y-3 text-sm">
              <p>Listo. Revisa tu correo y haz clic en el link para entrar.</p>
              <p className="text-muted-foreground">
                ¿No llega? Revisa spam, o verifica que sea el correo con el que te invitaron.
              </p>
              <Button variant="outline" className="w-full" onClick={() => setEnviado(false)}>
                Usar otro correo
              </Button>
              {process.env.NODE_ENV === "development" && (
                <p className="text-muted-foreground">
                  Modo desarrollo: el link también se imprime en el log de la API.
                </p>
              )}
            </div>
          ) : (
            <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="email">Correo</Label>
                <Input
                  id="email"
                  type="email"
                  placeholder="tu@correo.com"
                  autoComplete="email"
                  autoFocus
                  {...register("email")}
                />
                {errors.email && (
                  <p className="text-sm text-destructive">{errors.email.message}</p>
                )}
              </div>
              <Button type="submit" className="w-full" disabled={isSubmitting}>
                {isSubmitting ? "Enviando..." : "Enviar link de acceso"}
              </Button>
              <p className="text-xs text-muted-foreground">
                El acceso es por invitación. Si no tienes cuenta, pídesela al administrador
                de tu marca.
              </p>
            </form>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
