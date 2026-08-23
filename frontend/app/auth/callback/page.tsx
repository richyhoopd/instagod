import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

export default function AuthCallbackPage() {
  return (
    <div className="flex min-h-svh items-center justify-center p-4">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle>Procesando acceso</CardTitle>
          <CardDescription>
            El link de acceso lo procesa la API directamente y te redirige. Si ves esta
            página, es posible que el link haya expirado o ya se haya usado.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Button asChild className="w-full">
            <Link href="/login">Pedir un nuevo link</Link>
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}
