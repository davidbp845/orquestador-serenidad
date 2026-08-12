import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'preact/hooks';

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

  // Testimonios largos (p.ej. el de Buddy) no caben en 3 líneas —
  // se truncan con line-clamp y, SOLO si de verdad desbordan
  // (scrollHeight > clientHeight), se ofrece un "Leer más" que abre
  // el testimonio completo en un diálogo con scroll. Testimonios
  // cortos no se tocan: sin recorte ni botón.
  const refsDescripcion = useRef(new Map<number, HTMLParagraphElement>());
  const [truncados, setTruncados] = useState<Set<number>>(new Set());
  const [testimonioAbierto, setTestimonioAbierto] = useState<Testimonio | null>(null);
  const dialogoRef = useRef<HTMLDialogElement>(null);

  const registrarRefDescripcion = useCallback(
    (id: number) => (el: HTMLParagraphElement | null) => {
      if (el) refsDescripcion.current.set(id, el);
      else refsDescripcion.current.delete(id);
    },
    [],
  );

  useLayoutEffect(() => {
    const siguiente = new Set<number>();
    refsDescripcion.current.forEach((el, id) => {
      if (el.scrollHeight > el.clientHeight + 1) siguiente.add(id);
    });
    setTruncados((actual) => {
      if (actual.size === siguiente.size && [...actual].every((id) => siguiente.has(id))) return actual;
      return siguiente;
    });
  });

  useEffect(() => {
    if (testimonioAbierto) dialogoRef.current?.showModal();
  }, [testimonioAbierto]);

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
                  <p
                    ref={registrarRefDescripcion(t.id)}
                    class={`mt-(--spacing-fluid-2xs) text-sm text-(--color-texto-suave) ${
                      // El ancho de la tarjeta es el mismo en vertical y en
                      // horizontal con 1 sola visible (misma columna del
                      // 30% del Hero) — solo hace falta acotar líneas
                      // cuando de verdad hay varias tarjetas compartiendo
                      // fila (tablet, visibles > 1), no por defecto.
                      direccion === 'horizontal' && visibles > 1 ? 'line-clamp-3' : ''
                    }`}
                  >
                    {t.descripcion}
                  </p>
                  {truncados.has(t.id) && (
                    <button
                      type="button"
                      onClick={() => setTestimonioAbierto(t)}
                      class="mt-(--spacing-fluid-3xs) self-start text-sm font-medium text-(--color-acento) hover:underline"
                    >
                      Leer más
                    </button>
                  )}
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
      <dialog
        ref={dialogoRef}
        onClose={() => setTestimonioAbierto(null)}
        onClick={(e) => {
          if (e.target === dialogoRef.current) dialogoRef.current?.close();
        }}
        class="m-auto max-h-[80vh] w-[90vw] max-w-md rounded-2xl border border-(--color-borde) bg-(--color-superficie) p-0 backdrop:bg-black/50"
      >
        {testimonioAbierto && (
          <div class="flex max-h-[80vh] flex-col">
            <div class="flex items-center justify-between border-b border-(--color-borde) p-(--spacing-fluid-s)">
              <p class="text-(--color-acento)">{'⭐'.repeat(testimonioAbierto.valoracion)}</p>
              <button
                type="button"
                onClick={() => dialogoRef.current?.close()}
                aria-label="Cerrar"
                class="rounded-full p-(--spacing-fluid-3xs) text-(--color-texto-suave) transition-colors hover:bg-(--color-acento-suave) hover:text-(--color-acento)"
              >
                <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
                  <path d="M18 6 6 18M6 6l12 12" />
                </svg>
              </button>
            </div>
            <div class="flex-1 overflow-y-auto p-(--spacing-fluid-s)">
              <p class="whitespace-pre-wrap text-sm text-(--color-texto-suave)">
                {testimonioAbierto.descripcion}
              </p>
            </div>
            <div class="border-t border-(--color-borde) p-(--spacing-fluid-s) text-sm font-medium text-(--color-texto)">
              — {testimonioAbierto.nombre}
              {testimonioAbierto.titulo && ` · ${testimonioAbierto.titulo}`}
            </div>
          </div>
        )}
      </dialog>
    </div>
  );
}
