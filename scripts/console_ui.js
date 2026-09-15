          (() => {
            const views = Array.from(document.querySelectorAll("[data-console-view]"));
            const viewLinks = Array.from(document.querySelectorAll("[data-console-view-link]"));
            if (!views.length) return;
            const qaMode = new URLSearchParams(location.search).get("qa") === "1";
            const recordUsage = (event, view) => {
              if (qaMode) return;
              fetch("/usage-event", {method:"POST", headers:{"Content-Type":"application/x-www-form-urlencoded"}, body:new URLSearchParams({event, view}), keepalive:true}).catch(() => {});
            };
            window.ultimusRecordUsage = recordUsage;
            const resolveView = (target) => {
              const legacyViews = {cartera: "decisiones", oportunidades: "decisiones"};
              const normalizedTarget = legacyViews[target] || target;
              const element = document.getElementById(normalizedTarget) || document.getElementById("view-" + normalizedTarget);
              return element?.closest("[data-console-view]")?.dataset.consoleView || "hoy";
            };
            let currentView = "";
            const showView = (name, remember = true) => {
              const selected = resolveView(name);
              views.forEach(view => { view.hidden = view.dataset.consoleView !== selected; });
              viewLinks.forEach(link => {
                if (link.dataset.consoleViewLink === selected) link.setAttribute("aria-current", "page");
                else link.removeAttribute("aria-current");
              });
              if (remember && currentView !== selected) recordUsage("VIEW_CHANGE", selected);
              currentView = selected;
              try { localStorage.setItem("stockUltimusConsoleView", selected); } catch (_) {}
            };
            const navigate = (target, remember = true) => {
              showView(target, remember);
              const element = document.getElementById(target) || document.getElementById("view-" + target);
              if (!element) return;
              let parent = element;
              while (parent) {
                if (parent.tagName === "DETAILS") parent.open = true;
                parent.hidden = false;
                parent = parent.parentElement;
              }
              if (element.matches("[data-position-card]")) {
                const search = document.getElementById("position-search");
                activePositionFilter = "all";
                setPressed(positionFilters, positionFilters.find(button => button.dataset.positionFilter === "all"));
                if (search) { search.value = ""; search.dispatchEvent(new Event("input")); }
                element.hidden = false;
              }
              const focus = element.matches("details") ? element.querySelector("summary") : element.querySelector("h2,h3") || element;
              focus.setAttribute("tabindex", "-1");
              focus.focus({preventScroll:true});
              element.scrollIntoView({block:"start"});
            };
            const saved = (() => { try { return localStorage.getItem("stockUltimusConsoleView"); } catch (_) { return null; } })();
            showView(location.hash.slice(1) || saved || "hoy", false);
            recordUsage("PAGE_VIEW", currentView);
            window.addEventListener("hashchange", () => navigate(location.hash.slice(1)));
            document.addEventListener("click", event => {
              const anchor = event.target.closest('a[href^="#"]');
              if (!anchor) return;
              const target = anchor.getAttribute("href").slice(1);
              if (location.hash === "#" + target) navigate(target);
            });
            const focusButton = document.querySelector("[data-focus-mode]");
            const applyFocus = enabled => {
              document.body.classList.toggle("focus-mode", enabled);
              if (focusButton) { focusButton.textContent = enabled ? "Salir de foco" : "Modo foco"; focusButton.setAttribute("aria-pressed", String(enabled)); }
              try { localStorage.setItem("stockUltimusFocusMode", enabled ? "1" : "0"); } catch (_) {}
            };
            let focusEnabled = false;
            try { focusEnabled = localStorage.getItem("stockUltimusFocusMode") === "1"; } catch (_) {}
            applyFocus(focusEnabled);
            if (focusButton) focusButton.addEventListener("click", () => {
              focusEnabled = !focusEnabled; applyFocus(focusEnabled);
              recordUsage(focusEnabled ? "FOCUS_ON" : "FOCUS_OFF", "hoy");
              location.hash = "view-hoy";
            });
            const setPressed = (buttons, active) => buttons.forEach(button => {
              button.classList.toggle("active", button === active);
              button.setAttribute("aria-pressed", String(button === active));
            });
            const search = document.getElementById("position-search");
            const cards = Array.from(document.querySelectorAll("[data-position-card]"));
            const empty = document.getElementById("position-search-empty");
            const status = document.getElementById("position-search-status");
            const positionFilters = Array.from(document.querySelectorAll("[data-position-filter]"));
            let activePositionFilter = "all";
            const applyPositionFilters = () => {
              const query = search.value.trim().toUpperCase();
              let visible = 0;
              cards.forEach((card) => {
                const matchesTicker = !query || (card.dataset.ticker || "").includes(query);
                const matchesQueue = activePositionFilter === "all" || card.dataset.priority === activePositionFilter;
                const matches = matchesTicker && matchesQueue;
                card.hidden = !matches;
                if (matches) visible += 1;
              });
              if (empty) empty.hidden = visible !== 0;
              if (status) status.textContent = query || activePositionFilter !== "all" ? `${visible} posición(es) en esta vista.` : "Selecciona una posición para ver su recomendación y alternativas.";
              if (query && visible === 1) cards.find((card) => !card.hidden)?.setAttribute("open", "");
            };
            if (search && cards.length) search.addEventListener("input", applyPositionFilters);
            positionFilters.forEach((button) => button.addEventListener("click", () => {
              activePositionFilter = button.dataset.positionFilter || "all";
              setPressed(positionFilters, button);
              applyPositionFilters();
            }));
            setPressed(positionFilters, positionFilters.find(button => button.dataset.positionFilter === "all"));
            document.querySelectorAll("[data-position-focus]").forEach(button => button.addEventListener("click", () => {
              activePositionFilter = "all";
              setPressed(positionFilters, positionFilters.find(button => button.dataset.positionFilter === "all"));
              if (search) search.value = "";
              applyPositionFilters();
              location.hash = button.dataset.positionFocus;
              navigate(button.dataset.positionFocus);
            }));

            const opportunityFilters = Array.from(document.querySelectorAll("[data-opportunity-filter]"));
            const opportunityCards = Array.from(document.querySelectorAll("[data-opportunity-card]"));
            const opportunityEmpty = document.getElementById("opportunity-filter-empty");
            const expireFutures = () => {
              document.querySelectorAll("[data-price-valid-until]").forEach((card) => {
                const deadline = Date.parse(card.dataset.priceValidUntil || "");
                if (!Number.isFinite(deadline) || Date.now() < deadline) return;
                if (!card.classList.contains("opportunity-ready") && !card.classList.contains("futures-ready")) return;
                card.classList.replace("opportunity-ready", "opportunity-forming");
                card.classList.replace("futures-ready", "futures-verify_price");
                const badge = card.querySelector(".opportunity-card-head b, .futures-primary-head b");
                const action = card.querySelector(".opportunity-action strong, .futures-recommendation");
                if (badge) badge.textContent = "Verificar precio actual";
                if (action) action.textContent = "Cotización fuera de vigencia; actualizar antes de entrar.";
              });
              document.querySelectorAll("[data-futures-expires-at]").forEach((card) => {
                const deadline = Date.parse(card.dataset.futuresExpiresAt || "");
                if (Number.isFinite(deadline) && Date.now() >= deadline) {
                  card.hidden = true;
                  card.dataset.expired = "true";
                }
              });
              const current = opportunityCards.filter((card) => card.dataset.expired !== "true");
              ["ready", "forming", "waiting", "blocked", "research"].forEach((state) => {
                const count = current.filter((card) => card.classList.contains("opportunity-" + state)).length;
                document.querySelectorAll(".opportunity-status-strip .status-" + state + " strong").forEach((node) => node.textContent = String(count));
                if (state === "ready") document.querySelectorAll("[data-live-ready-count]").forEach((node) => node.textContent = String(count));
              });
              opportunityFilters.forEach((button) => {
                const kind = button.dataset.opportunityFilter || "all";
                const count = kind === "all" ? current.length : current.filter((card) => card.dataset.opportunityType === kind).length;
                button.textContent = button.textContent.replace(/\(\d+\)/, "(" + count + ")");
              });
            };
            expireFutures();
            window.setInterval(() => { expireFutures(); document.dispatchEvent(new Event("futures-expired")); }, 1000);
            let quotesBusy = false;
            const refreshFuturesPrices = async () => {
              const cards = Array.from(document.querySelectorAll("[data-futures-signal-key]")).filter((card) => card.dataset.futuresSignalKey && card.dataset.expired !== "true");
              if (quotesBusy || document.hidden || !cards.length) return;
              quotesBusy = true;
              try {
                const response = await fetch("/futures-live-prices", {signal: AbortSignal.timeout(8000)});
                if (!response.ok) return;
                const payload = await response.json();
                if (!Array.isArray(payload.items)) return;
                cards.forEach((card) => {
                  const item = payload.items.find((item) => item.signal_key === card.dataset.futuresSignalKey);
                  if (!item) { card.hidden = true; card.dataset.expired = "true"; return; }
                  const prefix = card.hasAttribute("data-opportunity-card") ? "opportunity-" : "futures-";
                  Array.from(card.classList).filter((value) => value.startsWith(prefix) && ["ready", "forming", "verify_price", "blocked", "confirmed", "detected", "watch"].includes(value.slice(prefix.length))).forEach((value) => card.classList.remove(value));
                  card.classList.add(prefix + item.state);
                  card.dataset.priceValidUntil = item.price_valid_until || "";
                  const badge = card.querySelector(".opportunity-card-head b, .futures-primary-head b");
                  const action = card.querySelector(".opportunity-action strong, .futures-recommendation");
                  if (badge) badge.textContent = item.state_label;
                  if (action) action.textContent = item.action;
                });
                expireFutures();
              } catch (_) { /* The existing 30-second expiry remains authoritative. */ }
              finally { quotesBusy = false; }
            };
            window.setInterval(refreshFuturesPrices, 5000);
            refreshFuturesPrices();
            const stateFilters = Array.from(document.querySelectorAll("[data-opportunity-state-filter]"));
            let selectedStrategy = "all", selectedState = "all";
            const applyOpportunityFilters = () => {
              let visible = 0;
              opportunityCards.forEach(card => {
                const show = card.dataset.expired !== "true" && (selectedStrategy === "all" || card.dataset.opportunityType === selectedStrategy) && (selectedState === "all" || card.dataset.opportunityState === selectedState);
                card.hidden = !show;
                if (show) visible++;
              });
              if (opportunityEmpty) opportunityEmpty.hidden = visible !== 0;
              for (const [id, strategy] of [["canslim-radar","canslim"],["alertas","futures"],["coberturas-rsp","rsp"]]) {
                const section = document.getElementById(id);
                if (section) section.hidden = selectedStrategy !== "all" && selectedStrategy !== strategy;
              }
            };
            opportunityFilters.forEach(button => button.addEventListener("click", () => {
              selectedStrategy = button.dataset.opportunityFilter || "all";
              setPressed(opportunityFilters, button); applyOpportunityFilters();
            }));
            stateFilters.forEach(button => button.addEventListener("click", () => {
              selectedState = button.dataset.opportunityStateFilter || "all";
              setPressed(stateFilters, button); applyOpportunityFilters();
            }));
            setPressed(opportunityFilters, opportunityFilters[0]);
            document.addEventListener("futures-expired", applyOpportunityFilters);
            // Explain labels to assistive technology without storing form contents.
            document.querySelectorAll('input:not([type="hidden"]),select,textarea').forEach((input, index) => {
              if (!input.id) input.id = "console-field-" + index;
              const label = input.previousElementSibling;
              if (label?.tagName === "LABEL") label.htmlFor = input.id;
              if (!input.labels?.length && !input.getAttribute("aria-label")) input.setAttribute("aria-label", input.placeholder || input.name.replaceAll("_", " ") || "Dato");
            });
            if (status) { status.setAttribute("role", "status"); status.setAttribute("aria-live", "polite"); }
            requestAnimationFrame(() => { if (location.hash) navigate(location.hash.slice(1), false); });

            const money = new Intl.NumberFormat("en-US", {style:"currency", currency:"USD"});
            document.querySelectorAll("[data-opportunity-simulator]").forEach((simulator) => {
              const input = simulator.querySelector("[data-simulator-quantity]");
              if (!input) return;
              const unitCapital = Number(simulator.dataset.unitCapital);
              const capacity = Number(simulator.dataset.capacity);
              const totalNode = simulator.querySelector("[data-simulator-total]");
              const remainingNode = simulator.querySelector("[data-simulator-remaining]");
              const useNode = simulator.querySelector("[data-simulator-use]");
              const statusNode = simulator.querySelector("[data-simulator-status]");
              const update = () => {
                const maximum = Math.max(1, Number(input.max) || 10);
                const quantity = Math.min(maximum, Math.max(1, Math.floor(Number(input.value) || 1)));
                input.value = String(quantity);
                const total = unitCapital * quantity;
                const remaining = capacity - total;
                if (totalNode) totalNode.textContent = money.format(total);
                if (remainingNode) remainingNode.textContent = money.format(Math.max(remaining, 0)) + (remaining < 0 ? " · insuficiente" : " · proyección");
                if (useNode) useNode.textContent = capacity > 0 ? `${((total / capacity) * 100).toFixed(2)}%` : "N/D";
                if (statusNode) statusNode.textContent = remaining < 0 ? "Capacidad insuficiente" : total / capacity > .25 ? "Viable; revisar tamaño" : "Viable por capacidad";
                simulator.classList.toggle("simulator-risk", remaining < 0 || (capacity > 0 && total / capacity > .25));
              };
              input.addEventListener("input", update);
              input.addEventListener("change", update);
              update();
            });
          })();

          (() => {
            const overlay = document.getElementById("busy-overlay");
            if (!overlay) return;
            const title = overlay.querySelector("strong");
            const detail = overlay.querySelector("span");
            document.querySelectorAll("form").forEach((form) => {
              form.addEventListener("submit", (event) => {
                const submitter = event.submitter;
                const actionValue = submitter && submitter.name === "action" ? submitter.value : "";
                const reasonInput = form.querySelector('input[name="reason"]');
                const fillPriceInput = form.querySelector('input[name="ibkr_fill_price"]');
                const fillQuantityInput = form.querySelector('input[name="ibkr_fill_quantity"]');
                const reasonRequired = ["REJECT_SETUP", "APPROVE_MANUAL_REVIEW", "JOURNAL_NOTE", "MARK_IBKR_APPLIED", "MARK_IBKR_NOT_APPLIED", "MARK_MISSED"].includes(actionValue);
                if (reasonRequired && reasonInput && !reasonInput.value.trim()) {
                  event.preventDefault();
                  reasonInput.setCustomValidity("Esta accion requiere nota/razon.");
                  reasonInput.reportValidity();
                  setTimeout(() => reasonInput.setCustomValidity(""), 1200);
                  return;
                }
                if (actionValue === "MARK_IBKR_APPLIED" && fillPriceInput && fillQuantityInput && (!fillPriceInput.value.trim() || !fillQuantityInput.value.trim())) {
                  event.preventDefault();
                  const target = !fillPriceInput.value.trim() ? fillPriceInput : fillQuantityInput;
                  target.setCustomValidity("IBKR aplicada requiere fill y cantidad para medir performance real.");
                  target.reportValidity();
                  setTimeout(() => target.setCustomValidity(""), 1600);
                  return;
                }
                if (submitter && submitter.name) {
                  let selectedAction = Array.from(form.querySelectorAll('input[type="hidden"]')).find(input => input.name === submitter.name) || form.querySelector("input[data-submitter-value]");
                  if (!selectedAction) {
                    selectedAction = document.createElement("input");
                    selectedAction.type = "hidden";
                    selectedAction.dataset.submitterValue = "true";
                    form.appendChild(selectedAction);
                  }
                  selectedAction.name = submitter.name;
                  selectedAction.value = submitter.value;
                }
                const manualStatus = submitter && submitter.name === "status" ? submitter.value : "";
                const manualReason = submitter && submitter.dataset ? submitter.dataset.reason : "";
                if (manualStatus && manualReason) {
                  const reason = form.querySelector('input[name="reason"]');
                  if (reason) reason.value = manualReason;
                }
                const label = form.dataset.busy || "Procesando accion local";
                const backgroundSubmit = form.dataset.backgroundSubmit === "true";
                title.textContent = label;
                detail.textContent = form.dataset.busyDetail || "Solicitud enviada. Veras confirmacion o un panel RUNNING/DONE en unos segundos.";
                overlay.hidden = false;
                const buttons = Array.from(form.querySelectorAll("button"));
                buttons.forEach((button) => {
                  button.dataset.originalText = button.dataset.originalText || button.textContent;
                  button.disabled = true;
                  button.textContent = "Trabajando...";
                });
                if (!backgroundSubmit) {
                  event.preventDefault();
                  overlay.hidden = true;
                  let feedback = form.querySelector(".form-feedback");
                  if (!feedback) { feedback = document.createElement("div"); feedback.className = "form-feedback"; feedback.setAttribute("role", "status"); form.appendChild(feedback); }
                  feedback.textContent = "Guardando; espera la confirmación…";
                  const usageView = document.querySelector("[data-console-view]:not([hidden])")?.dataset.consoleView || "hoy";
                  window.ultimusRecordUsage?.("TASK_STARTED", usageView);
                  const isTask = new URL(form.action).pathname === "/daily-task-action";
                  fetch(form.action, {method:"POST", body:new URLSearchParams(new FormData(form)), headers:{Accept:isTask ? "application/json" : "text/html"}})
                    .then(async response => {
                      let message;
                      if (isTask) {
                        const payload = await response.json(); message = payload.message;
                        if(response.ok) { const state = form.closest(".operator-task")?.querySelector(".daily-task-actions em"); if(state) state.textContent = {DONE:"Revisado por hoy",POSTPONED:"Revisión pospuesta",REVIEWING:"En revisión",NEW:"Pendiente"}[payload.state] || "Estado actualizado"; }
                      } else {
                        const html = new DOMParser().parseFromString(await response.text(), "text/html");
                        message = html.querySelector(".console-message")?.textContent;
                      }
                      if (!response.ok) throw new Error(message || "No se pudo guardar. Reintenta; tus datos permanecen aquí.");
                      window.ultimusRecordUsage?.("TASK_COMPLETED", usageView);
                      feedback.textContent = message || "Solicitud procesada. Consulta el estado actualizado para confirmar el resultado.";
                      const refresh = document.createElement("a"); refresh.href = location.href; refresh.textContent = " Ver estado actualizado"; feedback.appendChild(refresh);
                      if (isTask && submitter.value !== "REOPEN") {
                        const undo = document.createElement("button"); undo.type = "button"; undo.textContent = "Deshacer revisión / posposición";
                        undo.addEventListener("click", async () => {
                          undo.disabled = true;
                          const body = new URLSearchParams(new FormData(form)); body.set("task_action", "REOPEN");
                          try {
                            const response = await fetch(form.action, {method:"POST",body,headers:{Accept:"application/json"}});
                            if (!response.ok) throw new Error("No se pudo deshacer");
                            feedback.textContent = "La tarea vuelve a estar pendiente. Su riesgo no se ha modificado.";
                            const state = form.closest(".operator-task")?.querySelector(".daily-task-actions em"); if(state) state.textContent="Pendiente";
                          } catch (_) { undo.disabled = false; feedback.append(" No pude confirmar; reintenta."); }
                        }); feedback.appendChild(undo);
                      }
                    })
                    .catch(error => { window.ultimusRecordUsage?.("TASK_FAILED", usageView); feedback.textContent = "No confirmado: " + error.message; })
                    .finally(() => buttons.forEach(button => { button.disabled = false; button.textContent = button.dataset.originalText; }));
                  return;
                }
                if (backgroundSubmit) {
                  event.preventDefault();
                  const statusTarget = form.dataset.statusTarget ? document.getElementById(form.dataset.statusTarget) : null;
                  if (statusTarget) statusTarget.textContent = "Refresh RSP solicitado. Esperando confirmacion local...";
                  fetch(form.action, {
                    method: (form.method || "post").toUpperCase(),
                    body: new URLSearchParams(new FormData(form)),
                    headers: { "Accept": "application/json" }
                  })
                    .then((response) => response.json())
                    .then((payload) => {
                      const job = payload.job_id ? " Job: " + payload.job_id : "";
                      const message = payload.message || (payload.ok ? "Proceso iniciado." : "No pude iniciar el proceso.");
                      title.textContent = payload.already_running ? "El proceso ya está corriendo" : "Proceso iniciado";
                      detail.textContent = message + job;
                      if (statusTarget) statusTarget.textContent = message + job;
                      if (payload.job_id && form.dataset.reloadOnDone === "true") {
                        const poll = () => fetch("/job-status?id=" + encodeURIComponent(payload.job_id), {headers: {"Accept": "application/json"}})
                          .then((response) => response.json())
                          .then((state) => {
                            const progress = state.progress || {};
                            const progressText = progress.total ? ` ${progress.completed || 0}/${progress.total} · ${progress.current || "finalizando"}` : "";
                            if (statusTarget) statusTarget.textContent = (state.label || "Actualización") + progressText;
                            if (state.status === "DONE") {
                              if (statusTarget) statusTarget.textContent = "Actualización terminada. Recargando datos…";
                              if (statusTarget) { const link = document.createElement("a"); link.href = location.href; link.textContent = " Ver datos actualizados"; statusTarget.appendChild(link); }
                              return;
                            }
                            if (state.status === "ERROR") {
                              title.textContent = "Actualización incompleta";
                              detail.textContent = state.error || "Revisa el resultado del proceso.";
                              if (statusTarget) statusTarget.textContent = "Actualización incompleta: " + (state.error || "fuente remota no disponible");
                              return;
                            }
                            window.setTimeout(poll, 900);
                          })
                          .catch(() => window.setTimeout(poll, 1600));
                        window.setTimeout(poll, 500);
                      }
                    })
                    .catch((error) => {
                      title.textContent = "Refresh RSP no confirmado";
                      detail.textContent = String(error || "Error local");
                      if (statusTarget) statusTarget.textContent = "No pude confirmar el refresh RSP. Revisa la consola.";
                    })
                    .finally(() => {
                      buttons.forEach((button) => {
                        button.disabled = false;
                        button.textContent = button.dataset.originalText || "Enviar";
                      });
                      setTimeout(() => { overlay.hidden = true; }, 1200);
                    });
                }
              });
            });
          })();

// Local activity filters do not alter operational records.
(() => {
  const cases = Array.from(document.querySelectorAll("[data-casefile]"));
  const search = document.getElementById("case-search"), phase = document.getElementById("case-phase"), date = document.getElementById("case-date");
  const apply = () => {
    let visible = 0;
    cases.forEach(card => {
      const matches = (!search.value || card.textContent.toUpperCase().includes(search.value.toUpperCase())) && (phase.value === "all" || (phase.value === "unlinked" ? card.dataset.caseLinked === "no" : card.dataset.casePhase === phase.value)) && (!date.value || card.dataset.caseDate.slice(0,10) >= date.value);
      card.hidden = !matches; if(matches) visible++;
    });
    const count = document.getElementById("case-count"); if(count) count.textContent = `${visible} casos en esta vista`;
  };
  if(search && phase && date) { [search,phase,date].forEach(control => control.addEventListener("input",apply)); apply(); }
  const activity = Array.from(document.querySelectorAll("[data-activity-at]"));
  const activityType = document.getElementById("activity-type");
  let lastVisit = null;
  let activitySince = null;
  const qa = new URLSearchParams(location.search).get("qa") === "1";
  try { lastVisit = localStorage.getItem("ultimusLastActivityVisit"); } catch (_) {}
  const filter = since => {
    activitySince = since;
    let count=0; activity.forEach(row => {
      const outsidePeriod = !!since && Date.parse(row.dataset.activityAt) <= Date.parse(since);
      const outsideType = activityType && activityType.value !== "all" && row.dataset.activityType !== activityType.value;
      row.hidden = outsidePeriod || outsideType; if(!row.hidden) count++;
    });
    const empty=document.getElementById("activity-empty"); if(empty) empty.hidden=count!==0;
  };
  activityType?.addEventListener("input",()=>filter(activitySince));
  document.getElementById("activity-since-last")?.addEventListener("click",()=>filter(lastVisit));
  document.getElementById("activity-show-all")?.addEventListener("click",()=>filter(null));
  const visited=()=>{ if(location.hash === "#view-historial" && !qa) { try {localStorage.setItem("ultimusLastActivityVisit",new Date().toISOString());} catch(_){} } };
  window.addEventListener("hashchange",visited); visited();
})();
