import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'preact/hooks';
import BurbujaMensaje from './BurbujaMensaje';
import IndicadorEscribiendo from './IndicadorEscribiendo';
import { useChatStream } from './useChatStream';

interface Props {
  apiBaseUrl: string;
  // Mensaje del botón CTA de la cabecera (issue #56) — configurable
  // por negocio, ver config/business.yaml::cta_cita.mensaje.
  ctaMensaje: string;
}

// Cadencia del efecto "como si fuese streaming" al escribir el mensaje
// del CTA letra a letra en el campo de texto, antes de enviarlo solo.
const MS_POR_CARACTER_CTA = 35;

function esperar(ms: number): Promise<void> {
  return new Promise((resolver) => setTimeout(resolver, ms));
}

// Ejemplos de preguntas que cubren lo que el asistente sabe hacer hoy
// (tools de application/tools.py + contenido del vault). Solo se
// muestran como sugerencias clicables a partir de sm: en móvil el
// hueco es demasiado justo y priorizamos que el campo de texto quede
// siempre visible sin hacer scroll.
//
// Las dos primeras son las únicas visibles sin expandir (ver
// primeraFilaSugerencias más abajo) — por eso la segunda es de
// intención de reserva directa, no solo informativa: la fila
// comprimida no debería ser solo preguntas, también un empujón hacia
// reservar en el primer clic (análisis de conversión, issue #79).
const SUGERENCIAS = [
  '¿Cuánto cuesta el masaje relajante de 60 min?',
  'Quiero reservar un masaje descontracturante',
  '¿Tenéis hueco mañana por la tarde?',
  '¿Cuál es vuestro horario de apertura?',
  '¿Dónde estáis ubicados?',
  '¿Tenéis alguna promoción activa?',
  '¿Puedo cancelar mi cita sin coste?',
  '¿Es seguro el masaje si estoy embarazada?',
  '¿Quién es la profesional que me atenderá?',
];

export default function ChatWidget({ apiBaseUrl, ctaMensaje }: Props) {
  const { mensajes, enviando, enviarMensaje } = useChatStream(apiBaseUrl);
  const [texto, setTexto] = useState('');
  const [expandido, setExpandido] = useState(true);
  // Dispara el flujo del CTA de la cabecera (issue #56): escribe el
  // mensaje letra a letra en el campo (efecto "streaming" del propio
  // mensaje del usuario, no de la respuesta), luego lo envía solo —
  // mismo camino que enviarMensaje ya usa para las sugerencias.
  const dispararCtaCita = useCallback(
    async (mensaje: string) => {
      if (!mensaje.trim() || enviando) return;
      setExpandido(true);
      for (let i = 1; i <= mensaje.length; i++) {
        setTexto(mensaje.slice(0, i));
        await esperar(MS_POR_CARACTER_CTA);
      }
      enviarMensaje(mensaje);
      setTexto('');
    },
    [enviando, enviarMensaje],
  );
  const finRef = useRef<HTMLDivElement>(null);
  const medidorRef = useRef<HTMLDivElement>(null);
  // Altura real de "sugerencias comprimidas" (intro + 1 fila de 2
  // botones), medida contra una réplica oculta siempre montada — así
  // conversación comprimida puede usar exactamente esa misma altura sin
  // depender de un valor fijo a mano que se desincronice si cambia el
  // diseño de las sugerencias.
  const [altoComprimido, setAltoComprimido] = useState<number | null>(null);
  // Tres modos distintos:
  // - Proponiendo preguntas, expandido: el área se ajusta al contenido
  //   (9 sugerencias). Correcto, sin cambios.
  // - Proponiendo preguntas, comprimido: solo 1 fila (2 sugerencias) —
  //   define "la altura comprimida" que se mide arriba.
  // - Conversación real, expandido: alto fijo grande (los mismos
  //   tamaños que ya se usaban antes del botón de comprimir).
  // - Conversación real, comprimido: la MISMA altura que "sugerencias
  //   comprimidas", sea cual sea el número de mensajes — con scroll
  //   vertical (ya autoscrollado al final) enseñando solo lo último.
  const hayConversacion = mensajes.length > 0;
  const primeraFilaSugerencias = SUGERENCIAS.slice(0, 2);
  const restoSugerencias = SUGERENCIAS.slice(2);

  useEffect(() => {
    finRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [mensajes, expandido]);

  // Avisa a otros widgets del Hero (Testimonios) de si el chat está
  // expandido o comprimido, ya que cada isla Preact vive aislada y esto
  // condiciona el espacio vertical/horizontal que les queda — mismo
  // patrón de CustomEvent en window que orquestador:fuentes.
  useEffect(() => {
    window.dispatchEvent(new CustomEvent('orquestador:chat-expandido', { detail: { expandido } }));
  }, [expandido]);

  useLayoutEffect(() => {
    const medir = () => {
      if (medidorRef.current) setAltoComprimido(medidorRef.current.offsetHeight);
    };
    medir();
    window.addEventListener('resize', medir);
    return () => window.removeEventListener('resize', medir);
  }, []);

  // Llegada desde otra página vía Cabecera.astro navegando a
  // "/?cta=cita" (issue #56): dispara el CTA al montar y limpia el
  // parámetro de la URL — eso mismo evita que el efecto se dispare de
  // nuevo si sus dependencias cambian, o al refrescar la página.
  useEffect(() => {
    const parametros = new URLSearchParams(window.location.search);
    if (parametros.get('cta') === 'cita') {
      window.history.replaceState(null, '', window.location.pathname);
      dispararCtaCita(ctaMensaje);
    }
  }, [ctaMensaje, dispararCtaCita]);

  // Clic en el CTA de la cabecera estando ya en la home: Cabecera.astro
  // despacha este evento directamente, sin navegar.
  useEffect(() => {
    const manejarAbrirChat = (evento: Event) => {
      const detalle = (evento as CustomEvent<{ mensaje: string }>).detail;
      if (detalle?.mensaje) dispararCtaCita(detalle.mensaje);
    };
    window.addEventListener('orquestador:abrir-chat', manejarAbrirChat);
    return () => window.removeEventListener('orquestador:abrir-chat', manejarAbrirChat);
  }, [dispararCtaCita]);

  const manejarEnvio = (evento: Event) => {
    evento.preventDefault();
    const texto_ = texto.trim();
    if (!texto_ || enviando) return;
    enviarMensaje(texto_);
    setTexto('');
  };

  const estiloAreaMensajes =
    hayConversacion && !expandido && altoComprimido
      ? { height: `${altoComprimido}px` }
      : undefined;

  return (
    <div class="relative flex flex-col overflow-hidden rounded-2xl border border-(--color-borde) bg-(--color-fondo)">
      {/* Réplica oculta de "sugerencias comprimidas" (intro + 1 fila),
          siempre montada, solo para medir su altura real y que
          conversación comprimida pueda igualarla exactamente. */}
      <div
        ref={medidorRef}
        aria-hidden="true"
        class="invisible absolute inset-x-0 top-0 -z-10 hidden p-(--spacing-fluid-s) sm:block"
      >
        <p class="text-base 2xl:text-lg">¿En qué podemos ayudarte? Prueba con algo así:</p>
        <div class="mt-(--spacing-fluid-2xs) grid grid-cols-2 gap-(--spacing-fluid-2xs)">
          {primeraFilaSugerencias.map((sugerencia) => (
            <button
              key={sugerencia}
              type="button"
              tabIndex={-1}
              class="rounded-xl border px-(--spacing-fluid-xs) py-(--spacing-fluid-3xs) text-left text-sm 2xl:text-base"
            >
              {sugerencia}
            </button>
          ))}
        </div>
      </div>
      <div
        style={estiloAreaMensajes}
        class={`space-y-(--spacing-fluid-2xs) overflow-y-auto p-(--spacing-fluid-s) ${
          hayConversacion
            ? expandido
              ? 'h-[min(70vh,32rem)] lg:h-[min(70vh,36rem)] 2xl:h-[min(70vh,44rem)]'
              : ''
            : 'flex-1 max-h-[min(70vh,32rem)] lg:max-h-[min(70vh,36rem)] 2xl:max-h-[min(70vh,44rem)]'
        }`}
      >
        {mensajes.length === 0 && (
          <div class="text-center">
            <p class="text-sm text-(--color-texto-suave) sm:hidden">
              Pregúntanos por precios, horarios o disponibilidad.
            </p>
            <div class="hidden sm:block">
              <p class="text-base text-(--color-texto-suave) 2xl:text-lg">
                ¿En qué podemos ayudarte? Prueba con algo así:
              </p>
              <div
                class={`grid grid-cols-2 gap-(--spacing-fluid-2xs) transition-[margin-top] duration-300 ease-in-out ${expandido ? 'mt-(--spacing-fluid-s)' : 'mt-(--spacing-fluid-2xs)'}`}
              >
                {primeraFilaSugerencias.map((sugerencia) => (
                  <button
                    key={sugerencia}
                    type="button"
                    onClick={() => enviarMensaje(sugerencia)}
                    disabled={enviando}
                    class={`rounded-xl border border-(--color-borde) bg-(--color-superficie) px-(--spacing-fluid-xs) text-left text-sm text-(--color-texto) transition-all duration-300 ease-in-out hover:border-(--color-acento) hover:bg-(--color-acento-suave) disabled:opacity-40 2xl:text-base ${expandido ? 'py-(--spacing-fluid-2xs)' : 'py-(--spacing-fluid-3xs)'}`}
                  >
                    {sugerencia}
                  </button>
                ))}
              </div>
              <div
                class="grid transition-[grid-template-rows] duration-300 ease-in-out"
                style={{ gridTemplateRows: expandido ? '1fr' : '0fr' }}
              >
                <div class="overflow-hidden">
                  <div
                    class="mt-(--spacing-fluid-2xs) grid grid-cols-2 gap-(--spacing-fluid-2xs) transition-opacity duration-300 ease-in-out"
                    style={{ opacity: expandido ? 1 : 0 }}
                  >
                    {restoSugerencias.map((sugerencia) => (
                      <button
                        key={sugerencia}
                        type="button"
                        onClick={() => enviarMensaje(sugerencia)}
                        disabled={enviando}
                        class="rounded-xl border border-(--color-borde) bg-(--color-superficie) px-(--spacing-fluid-xs) py-(--spacing-fluid-2xs) text-left text-sm text-(--color-texto) transition-colors hover:border-(--color-acento) hover:bg-(--color-acento-suave) disabled:opacity-40 2xl:text-base"
                      >
                        {sugerencia}
                      </button>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}
        {mensajes.map((m) =>
          m.rol === 'asistente' && m.enCurso && m.texto === '' ? (
            <IndicadorEscribiendo key={m.id} />
          ) : (
            <BurbujaMensaje key={m.id} mensaje={m} />
          ),
        )}
        <div ref={finRef} />
      </div>
      <form
        onSubmit={manejarEnvio}
        class="flex gap-(--spacing-fluid-2xs) border-t border-(--color-borde) px-(--spacing-fluid-2xs) py-(--spacing-fluid-3xs)"
      >
        <input
          value={texto}
          onInput={(e) => setTexto((e.target as HTMLInputElement).value)}
          placeholder="Escribe tu mensaje…"
          class="flex-1 rounded-full border border-(--color-borde) bg-(--color-superficie) px-(--spacing-fluid-xs) py-(--spacing-fluid-2xs) text-sm text-(--color-texto) outline-none focus:border-(--color-acento)"
        />
        <button
          type="submit"
          aria-disabled={enviando || !texto.trim()}
          class="rounded-full bg-(--color-acento) px-(--spacing-fluid-s) py-(--spacing-fluid-2xs) text-sm font-medium text-white aria-disabled:opacity-40"
        >
          Enviar
        </button>
        <button
          type="button"
          onClick={() => setExpandido((v) => !v)}
          aria-label={expandido ? 'Comprimir respuesta' : 'Expandir respuesta'}
          title={expandido ? 'Comprimir respuesta' : 'Expandir respuesta'}
          class="inline-flex shrink-0 items-center justify-center rounded-full border border-(--color-borde) bg-(--color-superficie) p-(--spacing-fluid-2xs) text-(--color-texto-suave) transition-colors hover:border-(--color-acento) hover:text-(--color-acento)"
        >
          <svg
            viewBox="0 0 24 24"
            width="18"
            height="18"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round"
            class="transition-transform duration-300 ease-in-out"
            style={{ transform: expandido ? 'rotate(180deg)' : 'rotate(0deg)' }}
          >
            <path d="M6 9l6 6 6-6" />
          </svg>
        </button>
      </form>
    </div>
  );
}
