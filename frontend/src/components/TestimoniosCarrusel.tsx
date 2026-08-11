import { useCallback, useEffect, useRef, useState } from 'preact/hooks';

interface Testimonio {
  id: number;
  nombre: string;
  titulo: string;
  descripcion: string;
  valoracion: number;
}

interface Props {
  apiBaseUrl: string;
  intervaloMs: number;
}

export default function TestimoniosCarrusel({ apiBaseUrl, intervaloMs }: Props) {
  const [testimonios, setTestimonios] = useState<Testimonio[]>([]);
  const [indice, setIndice] = useState(0);
  const [enPausa, setEnPausa] = useState(false);

  useEffect(() => {
    let cancelado = false;
    fetch(`${apiBaseUrl}/testimonios`)
      .then((respuesta) => (respuesta.ok ? respuesta.json() : []))
      .then((datos) => {
        if (!cancelado) setTestimonios(datos);
      })
      .catch(() => {
        if (!cancelado) setTestimonios([]);
      });
    return () => {
      cancelado = true;
    };
  }, [apiBaseUrl]);

  useEffect(() => {
    if (testimonios.length <= 1 || enPausa) return;
    const id = setInterval(() => {
      setIndice((i) => (i + 1) % testimonios.length);
    }, intervaloMs);
    return () => clearInterval(id);
  }, [testimonios.length, intervaloMs, enPausa]);

  // Pausa la rotación mientras el usuario interactúa (hover/foco en los
  // dots) — evita que un testimonio cambie mientras se está leyendo o
  // eligiendo otro a mano.
  const pausar = useCallback(() => setEnPausa(true), []);
  const reanudar = useCallback(() => setEnPausa(false), []);

  if (testimonios.length === 0) return null;

  const testimonio = testimonios[indice];

  return (
    <div
      class="rounded-2xl border border-(--color-borde) bg-(--color-superficie) p-(--spacing-fluid-s)"
      onMouseEnter={pausar}
      onMouseLeave={reanudar}
      onFocusIn={pausar}
      onFocusOut={reanudar}
    >
      <div aria-live="polite" class="min-h-[9rem]">
        <p class="text-(--color-acento)">{'⭐'.repeat(testimonio.valoracion)}</p>
        {testimonio.titulo && (
          <p class="mt-(--spacing-fluid-3xs) font-semibold text-(--color-texto)">{testimonio.titulo}</p>
        )}
        <p class="mt-(--spacing-fluid-2xs) text-sm text-(--color-texto-suave)">
          {testimonio.descripcion}
        </p>
        <p class="mt-(--spacing-fluid-2xs) text-sm font-medium text-(--color-texto)">
          — {testimonio.nombre}
        </p>
      </div>
      {testimonios.length > 1 && (
        <div class="mt-(--spacing-fluid-s) flex justify-center gap-(--spacing-fluid-3xs)">
          {testimonios.map((t, i) => (
            <button
              key={t.id}
              type="button"
              onClick={() => setIndice(i)}
              aria-label={`Ver testimonio de ${t.nombre}`}
              aria-current={i === indice}
              class={`h-2.5 w-2.5 rounded-full transition-colors ${
                i === indice ? 'bg-(--color-acento)' : 'bg-(--color-borde)'
              }`}
            />
          ))}
        </div>
      )}
    </div>
  );
}
