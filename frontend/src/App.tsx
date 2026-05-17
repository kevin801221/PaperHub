import { Toaster } from "@/components/ui/sonner";

function App() {
  return (
    <div className="min-h-screen bg-background text-foreground">
      <main className="container py-10">
        <h1 className="text-2xl font-semibold">PaperHub</h1>
        <p className="text-muted-foreground mt-2">Plan B in progress.</p>
      </main>
      <Toaster />
    </div>
  );
}

export default App;
