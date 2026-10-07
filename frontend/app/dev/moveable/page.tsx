import { notFound } from "next/navigation";
import { Banco } from "./banco";

export default function Page() {
  if (process.env.NODE_ENV === "production") notFound();
  return <Banco />;
}
