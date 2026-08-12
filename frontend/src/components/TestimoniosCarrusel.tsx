import { useCallback, useEffect, useState } from 'preact/hooks';

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

// Mismos breakpoints que usa Tailwind por defecto (sm/md/lg) — 'lg' es
// también el punto en el que Hero.astro pasa de columna apilada
// (grid-cols-1) a columnas lado a lado (lg:grid-cols-[70%_30%]), así
// que coincide con el momento real en que el widget deja de estar
// "debajo del chat" para estar "al lado".
type Anchura = 'movil' | 'sm' | 'md' | 'lg';

function usarAnchuraBreakpoint(): Anchura {
  const [anchura, setAnchura] = useState<Anchura>('movil');

  useEffect(() => {
    const consultas: [Anchura, MediaQueryList][] = [
      ['sm', window.matchMedia('(min-width: 640px)')],
      ['md', window.matchMedia('(min-width: 768px)')],
      ['lg', window.matchMedia('(min-width: 1024px)')],
    ];
    const recalcular = () => {
      const activo = consultas.filter(([, mq]) => mq.matches).map(([nombre]) => nombre);
      if (activo.includes('lg')) setAnchura('lg');
      else if (activo.includes('md')) setAnchura('md');
      else if (activo.includes('sm')) setAnchura('sm');
      else setAnchura('movil');
    };
    recalcular();
    consultas.forEach(([, mq]) => mq.addEventListener('change', recalcular));
    return () => consultas.forEach(([, mq]) => mq.removeEventListener('change', recalcular));
  }, []);

  return anchura;
}

// El chat (isla Preact hermana) despacha este evento al expandirse o
// comprimirse (ver ChatWidget.tsx) — condiciona si a este widget le
// queda una columna alta (vertical) o una franja baja (horizontal).
function usarChatExpandido(): boolean {
  const [expandido, setExpandido] = useState(true);

  useEffect(() => {
    const manejar = (evento: Event) => {
      const detalle = (evento as CustomEvent<{ expandido: boolean }>).detail;
      if (detalle) setExpandido(detalle.expandido);
    };
    window.addEventListener('orquestador:chat-expandido', manejar);
    return () => window.removeEventListener('orquestador:chat-expandido', manejar);
  }, []);

  return expandido;
}

// Antes de tener el listado, no había forma de distinguir "aún
// cargando" de "cargó y no hay testimonios" (ambos eran un array
// vacío) — el widget se quedaba invisible hasta que el fetch
// resolviera, sin placeholder ni reintento, así que un fallo puntual
// (backend arrancando, CORS lento) lo dejaba vacío para siempre hasta
// un refresh manual.
//
// El backend carga Chroma + el modelo de embeddings antes de
// escuchar en el puerto, lo que puede tardar bastante más que un
// único reintento corto — así que un fallo de red (backend aún no
// arriba) se reintenta indefinidamente con backoff creciente hasta
// que responda, en vez de rendirse tras un intento y dejar el widget
// vacío hasta un refresh manual. Un fallo de "sí responde pero no
// más allá" (respuesta.ok=false) no se reintenta: es un estado
// legítimo, no indica que el backend siga arrancando.
const REINTENTO_MS_INICIAL = 1500;
const REINTENTO_MS_MAXIMO = 15000;

export default function TestimoniosCarrusel({ apiBaseUrl, intervaloMs }: Props) {
  const [testimonios, setTestimonios] = useState<Testimonio[]>([]);
  const [cargando, setCargando] = useState(true);
  const [pagina, setPagina] = useState(0);
  const [enPausa, setEnPausa] = useState(false);
  const anchura = usarAnchuraBreakpoint();
  const chatExpandido = usarChatExpandido();

  useEffect(() => {
    let cancelado = false;
    let temporizador: ReturnType<typeof setTimeout> | undefined;

    const cargar = (esperaSiFallaMs: number) => {
      fetch(`${apiBaseUrl}/testimonios`)
        .then((respuesta) => (respuesta.ok ? respuesta.json() : []))
        .then((datos) => {
          if (cancelado) return;
          setTestimonios(datos);
          setCargando(false);
        })
        .catch(() => {
          if (cancelado) return;
          temporizador = setTimeout(() => {
            if (!cancelado) cargar(Math.min(esperaSiFallaMs * 2, REINTENTO_MS_MAXIMO));
          }, esperaSiFallaMs);
        });
    };
    cargar(REINTENTO_MS_INICIAL);
    return () => {
      cancelado = true;
      if (temporizador) clearTimeout(temporizador);
    };
  }, [apiBaseUrl]);

  const esDesktop = anchura === 'lg';
  // Desktop + chat expandido: el widget queda en una columna vertical
  // alta → varios testimonios apilados, carrusel en vertical. Desktop +
  // chat comprimido, o tablet/móvil (el widget siempre queda debajo del
  // chat ahí, en horizontal): franja baja → carrusel en horizontal.
  const direccion: 'vertical' | 'horizontal' = esDesktop && chatExpandido ? 'vertical' : 'horizontal';
  const visibles = esDesktop
    ? chatExpandido
      ? 3
      : 1
    : anchura === 'md'
      ? 3
      : anchura === 'sm'
        ? 2
        : 1;

  const totalPaginas = Math.max(1, Math.ceil(testimonios.length / visibles));

  // Si visibles/testimonios cambian (p.ej. al redimensionar) y la página
  // actual queda fuera de rango, la recorta en vez de dejarla apuntando
  // a un hueco vacío.
  useEffect(() => {
    setPagina((p) => Math.min(p, totalPaginas - 1));
  }, [totalPaginas]);

  useEffect(() => {
    if (totalPaginas <= 1 || enPausa) return;
    const id = setInterval(() => {
      setPagina((p) => (p + 1) % totalPaginas);
    }, intervaloMs);
    return () => clearInterval(id);
  }, [totalPaginas, intervaloMs, enPausa]);

  // Pausa la rotación mientras el usuario interactúa (hover/foco en los
  // dots) — evita que la página cambie mientras se está leyendo o
  // eligiendo otra a mano.
  const pausar = useCallback(() => setEnPausa(true), []);
  const reanudar = useCallback(() => setEnPausa(false), []);

  if (cargando) {
    // Mismo contenedor y misma rejilla (visibles/dirección) que el
    // widget ya cargado, para no dar salto de layout cuando lleguen
    // los datos — solo cambian las tarjetas por bloques en animate-pulse.
    return (
      <div class="rounded-2xl border border-(--color-borde) bg-(--color-superficie) p-(--spacing-fluid-s)">
        <div
          class={`grid ${direccion === 'vertical' ? 'gap-(--spacing-fluid-m)' : 'gap-(--spacing-fluid-s)'}`}
          style={{
            gridTemplateColumns: direccion === 'horizontal' ? `repeat(${visibles}, minmax(0, 1fr))` : undefined,
          }}
        >
          {Array.from({ length: visibles }, (_, i) => (
            <div key={i} class="flex animate-pulse flex-col gap-(--spacing-fluid-2xs)">
              <div class="h-4 w-20 rounded bg-(--color-borde)" />
              <div class="h-3 w-full rounded bg-(--color-borde)" />
              <div class="h-3 w-5/6 rounded bg-(--color-borde)" />
              <div class="h-3 w-2/5 rounded bg-(--color-borde)" />
            </div>
          ))}
        </div>
      </div>
    );
  }

  if (testimonios.length === 0) return null;

  return (
    <div
      class="rounded-2xl border border-(--color-borde) bg-(--color-superficie) p-(--spacing-fluid-s)"
      onMouseEnter={pausar}
      onMouseLeave={reanudar}
      onFocusIn={pausar}
      onFocusOut={reanudar}
    >
      <div class="overflow-hidden" aria-live="polite">
        <div
          class={`flex transition-transform duration-500 ease-in-out ${
            direccion === 'vertical' ? 'flex-col' : 'flex-row'
          }`}
          style={{
            transform:
              direccion === 'vertical' ? `translateY(-${pagina * 100}%)` : `translateX(-${pagina * 100}%)`,
          }}
        >
          {Array.from({ length: totalPaginas }, (_, p) => (
            <div
              key={p}
              class={`grid w-full shrink-0 ${
                direccion === 'vertical' ? 'gap-(--spacing-fluid-m)' : 'gap-(--spacing-fluid-s)'
              }`}
              style={{
                gridTemplateColumns:
                  direccion === 'horizontal' ? `repeat(${visibles}, minmax(0, 1fr))` : undefined,
              }}
            >
              {testimonios.slice(p * visibles, p * visibles + visibles).map((t) => (
                <article key={t.id} class="flex flex-col overflow-hidden">
                  <p class="text-(--color-acento)">{'⭐'.repeat(t.valoracion)}</p>
                  <p class="mt-(--spacing-fluid-2xs) text-sm text-(--color-texto-suave)">{t.descripcion}</p>
                  <p class="mt-(--spacing-fluid-2xs) text-sm font-medium text-(--color-texto)">
                    — {t.nombre}
                    {t.titulo && ` · ${t.titulo}`}
                  </p>
                </article>
              ))}
            </div>
          ))}
        </div>
      </div>
      {totalPaginas > 1 && (
        <div class="mt-(--spacing-fluid-s) flex justify-center gap-(--spacing-fluid-3xs)">
          {Array.from({ length: totalPaginas }, (_, p) => (
            <button
              key={p}
              type="button"
              onClick={() => setPagina(p)}
              aria-label={`Ver testimonios ${p * visibles + 1}–${Math.min((p + 1) * visibles, testimonios.length)}`}
              aria-current={p === pagina}
              class={`h-2.5 w-2.5 rounded-full transition-colors ${
                p === pagina ? 'bg-(--color-acento)' : 'bg-(--color-borde)'
              }`}
            />
          ))}
        </div>
      )}
    </div>
  );
}
