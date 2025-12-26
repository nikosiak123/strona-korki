const availableLevels = [
    { label: "Szkoła podstawowa", value: "podstawowka" },
    { label: "Liceum - poziom podstawowy", value: "liceum_podstawa" },
    { label: "Liceum - poziom rozszerzony", value: "liceum_rozszerzenie" },
    { label: "Technikum - poziom podstawowy", value: "liceum_podstawa" }, // Uwaga: technikum używa tych samych tagów
    { label: "Technikum - poziom rozszerzony", value: "liceum_rozszerzenie" }
];

document.addEventListener('DOMContentLoaded', async () => {
    const loadingState = document.getElementById('loadingState');
    const contentDiv = document.getElementById('content');
    const scheduleForm = document.getElementById('scheduleForm');
    const welcomeTutor = document.getElementById('welcomeTutor');
    const scheduleFields = document.getElementById('scheduleFields');
    const calendarContainer = document.getElementById('calendar-container');
    const upcomingLessonsContainer = document.getElementById('upcomingLessonsContainer');
    
    const lessonDetailsModal = document.getElementById('lessonDetailsModal');
    const modalDetailsContent = document.getElementById('modalDetailsContent');
    const modalCloseBtn = document.getElementById('modalCloseBtn');
    const actionModal = document.getElementById('actionModal');
    const actionModalTitle = document.getElementById('actionModalTitle');
    const actionModalText = document.getElementById('actionModalText');
    const actionModalButtons = document.getElementById('actionModalButtons');

    const API_BASE_URL = 'https://zakręcone-korepetycje.pl'; // Zmień na URL produkcyjny
    const daysOfWeek = ["Poniedziałek", "Wtorek", "Środa", "Czwartek", "Piątek", "Sobota", "Niedziela"]; // Zmieniona lista na pełne nazwy
    const daysOfWeekAPI = ["Poniedzialek", "Wtorek", "Sroda", "Czwartek", "Piatek", "Sobota", "Niedziela"]; // Nazwy używane przez API (bez polskich znaków)
    const daysOfWeekShort = ["Pon", "Wt", "Śr", "Czw", "Pt", "Sob", "Niedz"]; // Lista skrótów do iteracji
    const monthNames = ["Sty", "Lut", "Mar", "Kwi", "Maj", "Cze", "Lip", "Sie", "Wrz", "Paź", "Lis", "Gru"];
    const dayNamesFull = ["Niedziela", "Poniedziałek", "Wtorek", "Środa", "Czwartek", "Piątek", "Sobota"];

    const params = new URLSearchParams(window.location.search);
    const tutorID = params.get('tutorID');
    let tutorName = "";
    let currentWeekStart = getMonday(new Date());
    let upcomingLessons = [];
    let masterScheduleTimes = []; // Tutaj przechowamy "główną" siatkę godzin

    if (!tutorID) {
        loadingState.innerHTML = '<h2>Błąd: Brak identyfikatora korepetytora w linku. Dostęp zabroniony.</h2>';
        return;
    }

    try {
        // Najpierw pobierz "główną" siatkę wszystkich możliwych godzin
        masterScheduleTimes = await fetchMasterSchedule();

        const data = await fetchTutorData(tutorID);
        tutorName = data['Imię i Nazwisko'];
        welcomeTutor.textContent = `Witaj, ${tutorName}!`;
        
        renderStaticScheduleForm(data);
        renderProfileForm(data);
        await fetchAndRenderUpcomingLessons(tutorName);
        await renderWeeklyCalendar(currentWeekStart);
        // Załaduj status godzin tygodniowo
        loadWeeklyHoursStatus();

        loadingState.style.display = 'none';
        contentDiv.style.display = 'block';

    } catch (error) {
        loadingState.innerHTML = `<h2>Wystąpił błąd: ${error.message}</h2>`;
    }

    scheduleForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const saveButton = document.getElementById('saveScheduleBtn');
        saveButton.textContent = 'Zapisywanie...';
        saveButton.disabled = true;
        
        // Używamy listy skróconej do pobierania danych z formularza
        const scheduleData = {};
        daysOfWeekShort.forEach(dayShort => {
            const start = document.querySelector(`input[name="${dayShort}_start"]`).value;
            const end = document.querySelector(`input[name="${dayShort}_end"]`).value;
            // Mapujemy na nazwę API (bez polskich znaków)
            const dayAPIName = daysOfWeekAPI[daysOfWeekShort.indexOf(dayShort)];
            scheduleData[dayAPIName] = (start && end) ? `${start}-${end}` : "";
        });

        try {
            const response = await fetch(`${API_BASE_URL}/api/update-tutor-schedule`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ tutorID: tutorID, schedule: scheduleData })
            });
            if (!response.ok) throw new Error("Nie udało się zapisać zmian.");
            const result = await response.json();
            alert(result.message);
        } catch (error) {
            alert(`Wystąpił błąd: ${error.message}`);
        } finally {
            saveButton.textContent = 'Zapisz stały grafik';
            saveButton.disabled = false;
        }
    });

    if(lessonDetailsModal) {
        modalCloseBtn.addEventListener('click', () => lessonDetailsModal.classList.remove('active'));
        lessonDetailsModal.addEventListener('click', (e) => {
            if (e.target === lessonDetailsModal) lessonDetailsModal.classList.remove('active');
        });
    }

    if(actionModal) {
        actionModal.addEventListener('click', (e) => {
            if (e.target === actionModal) actionModal.classList.remove('active');
        });
    }
    
    async function fetchMasterSchedule() {
        try {
            const response = await fetch(`${API_BASE_URL}/api/get-master-schedule`);
            if (!response.ok) throw new Error("Błąd pobierania głównego grafiku.");
            return await response.json();
        } catch (error) {
            console.error("Krytyczny błąd:", error);
            return [];
        }
    }

    async function fetchAndRenderUpcomingLessons(name) {
        try {
            const response = await fetch(`${API_BASE_URL}/api/get-tutor-lessons?tutorName=${name}`);
            if (!response.ok) throw new Error("Błąd pobierania listy lekcji.");
            
            upcomingLessons = await response.json();

            if (upcomingLessons.length > 0) {
                upcomingLessonsContainer.innerHTML = '';
                upcomingLessons.forEach((lesson, index) => {
                    const lessonElement = document.createElement('div');
                    lessonElement.className = 'lesson-list-item';
                    lessonElement.dataset.lessonIndex = index;
                    lessonElement.innerHTML = `
                        <div class="lesson-summary">
                            <span class="time">${lesson.date} o ${lesson.time}</span>
                            <span class="student">${lesson.studentName}</span>
                        </div>
                    `;
                    upcomingLessonsContainer.appendChild(lessonElement);
                    lessonElement.addEventListener('click', () => showLessonDetailsModal(index));
                });
            } else {
                upcomingLessonsContainer.innerHTML = '<p>Brak nadchodzących lekcji.</p>';
            }
        } catch (error) {
            upcomingLessonsContainer.innerHTML = `<p style="color: red;">${error.message}</p>`;
        }
    }

    function showLessonDetailsModal(lessonOrIndex) {
        const lesson = typeof lessonOrIndex === 'number' ? upcomingLessons[lessonOrIndex] : lessonOrIndex;
        if (!lesson) return;

        console.log("Dane dla showLessonDetailsModal:", lesson);

        let lessonTypeHtml = '';
        if (lesson.isTest) {
            lessonTypeHtml = `<div class="modal-details-item"><strong>Typ lekcji:</strong> <span style="color: #1976D2; font-weight: bold;">TESTOWA</span></div>`;
        } else {
            lessonTypeHtml = `<div class="modal-details-item"><strong>Typ lekcji:</strong> <span>STAŁA</span></div>`;
        }

        let paymentStatusHtml = '';
        if (lesson.isTest && !lesson.isPaid) {
            paymentStatusHtml = `<div class="modal-details-item" style="background-color: #FFF8E1; padding: 0.5rem; border-radius: 4px;"><strong>Płatność:</strong> <span style="color: #D32F2F; font-weight: bold;">TESTOWA - PRZYPOMNIJ O PŁATNOŚCI</span></div>`;
        } else if (lesson.isPaid) {
            paymentStatusHtml = `<div class="modal-details-item"><strong>Płatność:</strong> <span style="color: green; font-weight: bold;">Opłacona</span></div>`;
        } else {
            paymentStatusHtml = `<div class="modal-details-item"><strong>Płatność:</strong> <span style="color: orange; font-weight: bold;">Oczekuje na płatność</span></div>`;
        }

        modalDetailsContent.innerHTML = `
            <div class="modal-details-item"><strong>Uczeń:</strong> <span>${lesson.studentName || 'Brak danych'}</span></div>
            <div class="modal-details-item"><strong>Termin:</strong> <span>${lesson.date} o ${lesson.time}</span></div>
            ${lessonTypeHtml}
            ${paymentStatusHtml} 
            <hr style="border: none; border-top: 1px solid #eee; margin: 1rem 0;">
            <div class="modal-details-item"><strong>Przedmiot:</strong> <span>${lesson.subject || 'Brak danych'}</span></div>
            <div class="modal-details-item"><strong>Typ szkoły:</strong> <span>${lesson.schoolType || 'N/A'}</span></div>
            <div class="modal-details-item"><strong>Poziom:</strong> <span>${lesson.schoolLevel || 'N/A'}</span></div>
            <div class="modal-details-item"><strong>Klasa:</strong> <span>${lesson.schoolClass || 'N/A'}</span></div>
            <div class="modal-details-item"><strong>Link Teams:</strong> <a href="${lesson.teamsLink || '#'}" target="_blank">Dołącz</a></div>
        `;
        lessonDetailsModal.classList.add('active');
    }

    function showActionModal(slot) {
        actionModalTitle.textContent = `Zarządzaj terminem (${slot.date} o ${slot.time})`;
        
        console.log("Dane dla showActionModal (z kalendarza):", slot);
        
        let contactLinkHtml = '';
        if (slot.studentContactLink) {
            contactLinkHtml = `<a href="${slot.studentContactLink}" target="_blank"> (Przejdź do profilu)</a>`;
        }
        
        let paymentStatusHtml = '';
        if (slot.isTest && !slot.isPaid) {
            paymentStatusHtml = `<div class="modal-details-item" style="background-color: #FFF8E1; padding: 0.5rem; border-radius: 4px;"><strong>Płatność:</strong> <span style="color: #D32F2F; font-weight: bold;">TESTOWA - PRZYPOMNIJ O PŁATNOŚCI</span></div>`;
        } else if (slot.isPaid) {
            paymentStatusHtml = `<div class="modal-details-item"><strong>Płatność:</strong> <span style="color: green; font-weight: bold;">Opłacona</span></div>`;
        } else {
            paymentStatusHtml = `<div class="modal-details-item"><strong>Płatność:</strong> <span style="color: orange; font-weight: bold;">Oczekuje na płatność</span></div>`;
        }
    
        let detailsHtml = `
            <div class="modal-details-item"><strong>Uczeń:</strong> <span>${slot.studentName || 'Brak danych'}${contactLinkHtml}</span></div>
            ${paymentStatusHtml}
            <hr style="border: none; border-top: 1px solid #eee; margin: 1rem 0;">
            <div class="modal-details-item"><strong>Przedmiot:</strong> <span>${slot.subject || 'Brak danych'}</span></div>
            <div class="modal-details-item"><strong>Typ szkoły:</strong> <span>${slot.schoolType || 'N/A'}</span></div>
            <div class="modal-details-item"><strong>Poziom:</strong> <span>${slot.schoolLevel || 'N/A'}</span></div>
            <div class="modal-details-item"><strong>Klasa:</strong> <span>${slot.schoolClass || 'N/A'}</span></div>
            <div class="modal-details-item"><strong>Link Teams:</strong> <a href="${slot.teamsLink || '#'}" target="_blank">Dołącz</a></div>
        `;
        
        actionModalText.innerHTML = detailsHtml;
    
        actionModalButtons.innerHTML = `
            <button class="modal-btn primary" id="rescheduleBtn">Przełóż zajęcia</button>
            <button class="modal-btn secondary" id="closeActionModalBtn">Anuluj</button>
        `;
        actionModal.classList.add('active');
    
        document.getElementById('closeActionModalBtn').onclick = () => actionModal.classList.remove('active');
        
        document.getElementById('rescheduleBtn').onclick = async () => {
            // ... (reszta funkcji bez zmian)
        };
    }


    async function renderWeeklyCalendar(startDate) {
        calendarContainer.innerHTML = '<p>Ładowanie grafiku...</p>';
        const mobileContainer = document.getElementById('calendar-mobile-container');
        if (mobileContainer) mobileContainer.innerHTML = '';
    
        const params = new URLSearchParams({ startDate: getFormattedDate(startDate), tutorName: tutorName });
    
        try {
            const response = await fetch(`${API_BASE_URL}/api/get-schedule?${params.toString()}`);
            if (!response.ok) throw new Error("Błąd ładowania grafiku.");
    
            const fullSchedule = await response.json();
    
            const scheduleMap = {};
            fullSchedule.forEach(slot => {
                if (!scheduleMap[slot.date]) scheduleMap[slot.date] = {};
                scheduleMap[slot.date][slot.time] = slot;
            });
    
            calendarContainer.innerHTML = '';
            const daysInWeek = Array.from({ length: 7 }, (_, i) => {
                const d = new Date(startDate);
                d.setDate(d.getDate() + i);
                return d;
            });
    
            const calendarNavigation = document.createElement('div');
            calendarNavigation.className = 'calendar-navigation';
            const firstDayFormatted = `${daysInWeek[0].getDate()} ${monthNames[daysInWeek[0].getMonth()]}`;
            const lastDayFormatted = `${daysInWeek[6].getDate()} ${monthNames[daysInWeek[6].getMonth()]}`;
            calendarNavigation.innerHTML = `<button id="prevWeek">Poprzedni tydzień</button><h3>${firstDayFormatted} - ${lastDayFormatted}</h3><button id="nextWeek">Następny tydzień</button>`;
            calendarContainer.appendChild(calendarNavigation);
    
            const table = document.createElement('table');
            table.className = 'calendar-grid-table';
            let headerRow = '<tr><th class="time-label">Godzina</th>';
            daysInWeek.forEach(day => { headerRow += `<th>${dayNamesFull[day.getDay()]}<br>${String(day.getDate()).padStart(2, '0')} ${monthNames[day.getMonth()]}</th>`; });
            headerRow += '</tr>';
            table.createTHead().innerHTML = headerRow;
            const tbody = table.createTBody();
            let masterTime = new Date(startDate); masterTime.setHours(8, 0, 0, 0);
            const endMasterTime = new Date(startDate); endMasterTime.setHours(22, 0, 0, 0);
            while (masterTime < endMasterTime) {
                const timeSlot = masterTime.toTimeString().substring(0, 5);
                const row = tbody.insertRow();
                row.insertCell().outerHTML = `<td class="time-label">${timeSlot}</td>`;
                daysInWeek.forEach(day => {
                    const cell = row.insertCell();
                    const formattedDate = getFormattedDate(day);
                    const slotData = scheduleMap[formattedDate] ? scheduleMap[formattedDate][timeSlot] : null;
                    const block = document.createElement('div');
                    block.className = 'time-block';
                    
                    // Sprawdź czy termin jest w przeszłości
                    const slotDateTime = new Date(`${formattedDate}T${timeSlot}:00`);
                    const isPast = slotDateTime < new Date();
                    
                    if (slotData) {
                        switch(slotData.status) {
                            case 'available': block.classList.add('available'); block.textContent = "Dostępny"; block.addEventListener('click', () => handleBlockClick(formattedDate, timeSlot)); break;
                            case 'booked_lesson': case 'cyclic_reserved': block.classList.add('booked-lesson'); block.textContent = slotData.studentName; block.addEventListener('click', () => showActionModal(slotData)); break;
                            case 'completed': block.classList.add('completed'); block.textContent = slotData.studentName; block.style.cursor = 'not-allowed'; break;
                            case 'rescheduled_by_tutor': block.classList.add('rescheduled'); block.textContent = "PRZENIESIONE"; block.style.cursor = 'not-allowed'; break;
                            case 'blocked_by_tutor': block.classList.add('unavailable'); block.textContent = "BLOKADA"; block.addEventListener('click', () => handleBlockClick(formattedDate, timeSlot)); break;
                            default: block.classList.add('unavailable'); block.textContent = "Przeniesione"; block.style.cursor = 'not-allowed';
                        }
                    } else { block.classList.add('disabled'); block.addEventListener('click', () => handleAddHocSlot(formattedDate, timeSlot)); }
                    
                    // Dodaj klasę 'past' jeśli termin był w przeszłości
                    if (isPast) {
                        block.classList.add('past');
                    }
                    
                    cell.appendChild(block);
                });
                masterTime.setMinutes(masterTime.getMinutes() + 70);
            }
            calendarContainer.appendChild(table);
            
            if (mobileContainer) {
                let mobileMasterTime = new Date(startDate); mobileMasterTime.setHours(8, 0, 0, 0);
                const mobileEndMasterTime = new Date(startDate); mobileEndMasterTime.setHours(22, 0, 0, 0);
                const allTimeSlots = [];
                while(mobileMasterTime < mobileEndMasterTime) {
                    allTimeSlots.push(mobileMasterTime.toTimeString().substring(0, 5));
                    mobileMasterTime.setMinutes(mobileMasterTime.getMinutes() + 70);
                }
    
                daysInWeek.forEach(day => {
                    const formattedDate = getFormattedDate(day);
                    const dayCard = document.createElement('div');
                    dayCard.className = 'mobile-day-card';
                    let dayHtmlContent = '';
    
                    allTimeSlots.forEach(timeSlot => {
                        const slotData = scheduleMap[formattedDate] ? scheduleMap[formattedDate][timeSlot] : null;
                        const block = document.createElement('div');
                        block.className = 'time-block';
                        
                        // Sprawdź czy termin jest w przeszłości
                        const slotDateTime = new Date(`${formattedDate}T${timeSlot}:00`);
                        const isPast = slotDateTime < new Date();
                        
                        if (slotData) {
                            switch(slotData.status) {
                                case 'available':
                                    block.classList.add('available');
                                    block.textContent = `${timeSlot} - Dostępny`;
                                    block.addEventListener('click', () => handleBlockClick(formattedDate, timeSlot));
                                    break;
                                case 'booked_lesson':
                                case 'cyclic_reserved':
                                    block.classList.add('booked-lesson');
                                    block.textContent = `${timeSlot} - ${slotData.studentName}`;
                                    block.addEventListener('click', () => showActionModal(slotData));
                                    break;
                                case 'rescheduled_by_tutor':
                                    block.classList.add('rescheduled');
                                    block.textContent = `${timeSlot} - PRZENIESIONE`;
                                    block.style.cursor = 'not-allowed';
                                    break;
                                case 'blocked_by_tutor':
                                    block.classList.add('unavailable');
                                    block.textContent = `${timeSlot} - BLOKADA`;
                                    block.addEventListener('click', () => handleBlockClick(formattedDate, timeSlot));
                                    break;
                                default:
                                     block.classList.add('unavailable');
                                     block.textContent = `${timeSlot} - Zajęty`;
                                     block.style.cursor = 'not-allowed';
                            }
                        } else {
                            block.classList.add('disabled');
                            block.textContent = `${timeSlot} - Niedostępny (poza grafikiem)`;
                            block.addEventListener('click', () => handleAddHocSlot(formattedDate, timeSlot));
                        }
                        
                        // Dodaj klasę 'past' jeśli termin był w przeszłości
                        if (isPast) {
                            block.classList.add('past');
                        }
                        
                        dayHtmlContent += block.outerHTML;
                    });
                    
                    dayCard.innerHTML = `<h4>${dayNamesFull[day.getDay()]}, ${day.getDate()} ${monthNames[day.getMonth()]}</h4>` + dayHtmlContent;
                    mobileContainer.appendChild(dayCard);
    
                    dayCard.querySelectorAll('.time-block').forEach(blockEl => {
                        const time = blockEl.textContent.split(' - ')[0];
                        const date = formattedDate;
                        const slotData = scheduleMap[date] ? scheduleMap[date][time] : null;
    
                        if (blockEl.classList.contains('available') || blockEl.classList.contains('unavailable')) {
                             blockEl.addEventListener('click', () => handleBlockClick(date, time));
                        } else if (blockEl.classList.contains('booked-lesson')) {
                             blockEl.addEventListener('click', () => showActionModal(slotData));
                        } else if (blockEl.classList.contains('disabled')) {
                             blockEl.addEventListener('click', () => handleAddHocSlot(date, time));
                        }
                    });
                });
            }
    
            document.getElementById('prevWeek').addEventListener('click', () => changeWeek(-7));
            document.getElementById('nextWeek').addEventListener('click', () => changeWeek(7));
    
        } catch (error) {
            console.error("Błąd podczas renderowania kalendarza:", error);
            calendarContainer.innerHTML = '<p style="color: red;">Błąd renderowania kalendarza.</p>';
        }
    }

    
    async function handleBlockClick(date, time) {
        const block = event.target;
        block.textContent = '...';
        try {
            const res = await fetch(`${API_BASE_URL}/api/block-single-slot`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ tutorID, tutorName, date, time })
            });
            if (!res.ok) throw new Error("Błąd serwera");
            await renderWeeklyCalendar(currentWeekStart);
        } catch (error) {
            alert("Nie udało się zaktualizować terminu.");
            await renderWeeklyCalendar(currentWeekStart);
        }
    }

    async function handleAddHocSlot(date, time) {
        const block = event.target;
        block.textContent = '...';
        
        if (!confirm(`Czy na pewno chcesz dodać jednorazowy, dostępny termin w dniu ${date} o godzinie ${time}?`)) {
            renderWeeklyCalendar(currentWeekStart);
            return;
        }

        try {
            const res = await fetch(`${API_BASE_URL}/api/add-adhoc-slot`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ tutorID, tutorName, date, time })
            });
            if (!res.ok) throw new Error("Błąd serwera");
            await renderWeeklyCalendar(currentWeekStart);
        } catch (error) {
            alert("Nie udało się dodać nowego terminu.");
            await renderWeeklyCalendar(currentWeekStart);
        }
    }

    function changeWeek(days) {
        currentWeekStart.setDate(currentWeekStart.getDate() + days);
        renderWeeklyCalendar(currentWeekStart);
    }
    
    async function fetchTutorData(id) {
        const response = await fetch(`${API_BASE_URL}/api/get-tutor-schedule?tutorID=${id}`);
        if (!response.ok) throw new Error('Nie udało się pobrać danych.');
        return await response.json();
    }
    
    function renderStaticScheduleForm(data) {
        scheduleFields.innerHTML = '';
        const formatTime = (timeStr) => {
            if (!timeStr) return '';
            const parts = timeStr.split(':');
            if (parts.length < 2) return '';
            const hour = String(parts[0]).padStart(2, '0');
            const minute = String(parts[1]).padStart(2, '0');
            return `${hour}:${minute}`;
        };
        daysOfWeekShort.forEach(dayShort => { // Iterujemy po skróconych nazwach
            const dayAPIName = daysOfWeekAPI[daysOfWeekShort.indexOf(dayShort)]; // Pobieramy nazwę API do pobrania danych
            const timeRange = data[dayAPIName] || "";
            const [startTime = '', endTime = ''] = timeRange.split('-');
            const row = document.createElement('div');
            row.className = 'day-row';
            
            row.innerHTML = `
                <div class="day-label">${dayShort}</div>
                <div class="time-inputs">
                    <input type="time" class="form-control" name="${dayShort}_start" value="${formatTime(startTime.trim())}">
                    <span>-</span>
                    <input type="time" class="form-control" name="${dayShort}_end" value="${formatTime(endTime.trim())}">
                </div>
            `;
            
            scheduleFields.appendChild(row);
        });
    }

    function getFormattedDate(date) {
        const yyyy = date.getFullYear();
        const mm = String(date.getMonth() + 1).padStart(2, '0');
        const dd = String(date.getDate()).padStart(2, '0');
        return `${yyyy}-${mm}-${dd}`;
    }
    function getMonday(d) {
        d = new Date(d);
        const day = d.getDay();
        const diff = d.getDate() - day + (day === 0 ? -6 : 1);
        return new Date(d.setDate(diff));
    }
    
    // === Funkcje dla limitu godzin tygodniowo ===
    
    async function loadWeeklyHoursStatus() {
        try {
            const response = await fetch(`${API_BASE_URL}/api/get-tutor-weekly-hours?tutorName=${encodeURIComponent(tutorName)}`);
            const data = await response.json();
            
            const statusDiv = document.getElementById('weeklyHoursStatus');
            
            if (data.hasLimit) {
                const percentage = Math.min((data.currentHours / data.weeklyLimit) * 100, 100);
                let color = '#28a745'; // zielony
                if (percentage >= 100) color = '#dc3545'; // czerwony
                else if (percentage >= 80) color = '#ffc107'; // pomarańczowy
                
                statusDiv.innerHTML = `
                    <h4>Status godzin w tym tygodniu (poniedziałek-niedziela)</h4>
                    <div class="progress-bar-container">
                        <div class="progress-bar" style="background: ${color}; width: ${percentage}%">
                            ${data.currentHours}h / ${data.weeklyLimit}h
                        </div>
                    </div>
                    <p style="margin-top: 10px; color: #6c757d;">
                        ${data.currentHours >= data.weeklyLimit ? 
                            '⚠️ Osiągnięto limit! Grafik nie jest widoczny dla nowych uczniów.' : 
                            `✅ Pozostało: ${data.weeklyLimit - data.currentHours}h`}
                    </p>
                `;
            } else {
                statusDiv.innerHTML = `
                    <p style="color: #6c757d;"><strong>Brak ustawionego limitu godzin</strong> - grafik zawsze widoczny (∞)</p>
                    <p>Zajęte w tym tygodniu: <strong>${data.currentHours} godz.</strong></p>
                `;
            }
        } catch (error) {
            console.error('Błąd pobierania statusu godzin:', error);
            document.getElementById('weeklyHoursStatus').innerHTML = '<p style="color: red;">Błąd ładowania danych.</p>';
        }
    }
    
    // Zapisanie limitu
    document.getElementById('saveLimitBtn')?.addEventListener('click', async () => {
        const limitInput = document.getElementById('weeklyLimit');
        const limit = limitInput.value.trim() === '' ? null : parseInt(limitInput.value);
        
        if (limit !== null && (limit < 0 || limit > 168)) {
            alert('Limit musi być liczbą od 0 do 168 lub pozostaw puste dla braku limitu.');
            return;
        }
        
        try {
            const response = await fetch(`${API_BASE_URL}/api/update-tutor-weekly-limit`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    tutorID: tutorID,
                    weeklyLimit: limit
                })
            });
            
            if (response.ok) {
                alert('Limit godzin został zaktualizowany!');
                loadWeeklyHoursStatus(); // Odśwież status
                limitInput.value = ''; // Wyczyść pole
            } else {
                const error = await response.json();
                alert(`Błąd: ${error.message || 'Nie udało się zapisać limitu'}`);
            }
        } catch (error) {
            console.error('Błąd zapisu limitu:', error);
            alert('Wystąpił błąd podczas zapisu.');
        }
    });
});

    function renderProfileForm(data) {
        const emailInput = document.getElementById('emailInput');
        const levelsContainer = document.getElementById('levelsContainer');
        
        // Wypełnij email
        emailInput.value = data.Email || '';
        
        // Wyczyść kontener poziomów
        levelsContainer.innerHTML = '';
        
        // Dodaj checkboxy dla poziomów
        availableLevels.forEach(level => {
            const checkboxDiv = document.createElement('div');
            checkboxDiv.style.display = 'flex';
            checkboxDiv.style.alignItems = 'center';
            checkboxDiv.style.gap = '0.5rem';
            
            const checkbox = document.createElement('input');
            checkbox.type = 'checkbox';
            checkbox.id = `level_${level.value}`;
            checkbox.value = level.value;
            checkbox.checked = (data.PoziomNauczania || []).includes(level.value);
            
            const label = document.createElement('label');
            label.htmlFor = `level_${level.value}`;
            label.textContent = level.label;
            label.style.fontWeight = '500';
            
            checkboxDiv.appendChild(checkbox);
            checkboxDiv.appendChild(label);
            levelsContainer.appendChild(checkboxDiv);
        });
        
        // Dodaj event listener dla zapisywania profilu
        const saveProfileBtn = document.getElementById('saveProfileBtn');
        saveProfileBtn.addEventListener('click', saveProfile);
    }
    
    async function saveProfile() {
        const emailInput = document.getElementById('emailInput');
        const selectedLevels = [];
        availableLevels.forEach(level => {
            const checkbox = document.getElementById(`level_${level.value}`);
            if (checkbox.checked) {
                selectedLevels.push(level.value);
            }
        });
        
        const saveButton = document.getElementById('saveProfileBtn');
        saveButton.textContent = 'Zapisywanie...';
        saveButton.disabled = true;
        
        try {
            const response = await fetch(`${API_BASE_URL}/api/update-tutor-profile`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    tutorID: tutorID,
                    PoziomNauczania: selectedLevels,
                    Email: emailInput.value.trim()
                })
            });
            if (!response.ok) throw new Error("Nie udało się zapisać zmian.");
            const result = await response.json();
            alert(result.message);
        } catch (error) {
            alert(`Wystąpił błąd: ${error.message}`);
        } finally {
            saveButton.textContent = 'Zapisz profil';
            saveButton.disabled = false;
        }
    }

// Funkcje pomocy
function openHelpModal() {
    document.getElementById('helpModal').classList.add('show');
}

function closeHelpModal() {
    document.getElementById('helpModal').classList.remove('show');
}

// Zamknij modal po kliknięciu gdzie indziej
document.addEventListener('click', function(event) {
    const modal = document.getElementById('helpModal');
    if (modal && event.target == modal) {
        modal.classList.remove('show');
    }
});
