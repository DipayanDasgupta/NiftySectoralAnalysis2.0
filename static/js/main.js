// static/js/main.js
document.addEventListener('DOMContentLoaded', function () {
    const updateApiKeysBtn = document.getElementById('updateApiKeysBtn');
    const analysisForm = document.getElementById('analysisForm');
    const runAnalysisBtn = document.getElementById('runAnalysisBtn');
    const loadingIndicator = document.getElementById('loading-indicator');
    const logsOutput = document.getElementById('logs-output');
    const clearLogsBtn = document.getElementById('clearLogsBtn');
    const resultsSummaryDiv = document.getElementById('results-summary');
    const sectorChartsContainer = document.getElementById('sector-charts-container');
    const sectorDetailsContainer = document.getElementById('sector-details-container');
    const errorMessagesContainer = document.getElementById('error-messages-container');
    const errorList = document.getElementById('error-list');

    // Access the sector-stock configuration passed from Flask
    // Ensure your Flask template renders this script block *after* the sectorStockConfigJson variable is defined.
    let SECTOR_STOCK_CONFIG = {};
    try {
        const configElement = document.getElementById('sectorStockConfig');
        if (configElement && configElement.textContent) {
            SECTOR_STOCK_CONFIG = JSON.parse(configElement.textContent);
        } else {
            console.warn("Sector-stock configuration not found in DOM. Stock selection might not work.");
        }
    } catch (e) {
        console.error("Error parsing sector-stock configuration:", e);
    }


    const MAX_LOG_ENTRIES = 300;
    let currentLogEntries = [];
    let activeCharts = {}; 

    // --- Utility Functions (escapeHtml, appendToLog, renderLogs, displayErrorMessages) ---
    // (Keep these as they were in the previous complete JS version)
    function displayErrorMessages(messages) {
        errorList.innerHTML = '';
        if (messages && messages.length > 0) {
            messages.forEach(msg => {
                const li = document.createElement('li');
                li.textContent = String(msg); 
                errorList.appendChild(li);
            });
            errorMessagesContainer.style.display = 'block';
        } else {
            errorMessagesContainer.style.display = 'none';
        }
    }
    
    function escapeHtml(unsafe) {
        if (unsafe === null || typeof unsafe === 'undefined') return '';
        return unsafe.toString()
             .replace(/&/g, "&")
             .replace(/</g, "<")
             .replace(/>/g, ">")
             .replace(/"/g, '"')
             .replace(/'/g, "'");
    }

    function appendToLog(logEntry) { 
        currentLogEntries.push(logEntry);
        if (currentLogEntries.length > MAX_LOG_ENTRIES) {
            currentLogEntries.shift(); 
        }
        renderLogs();
    }

    function renderLogs() {
        logsOutput.innerHTML = ''; 
        currentLogEntries.forEach(logEntry => {
            const logElement = document.createElement('div');
            logElement.classList.add('log-entry');
            const levelStr = logEntry.level ? logEntry.level.toUpperCase() : 'UNKNOWN';
            logElement.innerHTML = `<span class="log-timestamp">[${logEntry.timestamp}]</span> <span class="log-level-${levelStr}">[${levelStr}]</span> ${escapeHtml(logEntry.message)}`;
            logsOutput.appendChild(logElement);
        });
        logsOutput.scrollTop = logsOutput.scrollHeight;
    }

    clearLogsBtn.addEventListener('click', () => {
        currentLogEntries = [];
        renderLogs(); 
        appendToLog({ timestamp: new Date().toLocaleTimeString([], { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit', fractionalSecondDigits: 3 }), message: "UI Logs cleared by user.", level: "INFO" });
    });

    // --- API Key Update --- (Keep as is)
     updateApiKeysBtn.addEventListener('click', async () => {
        const geminiKeySess = document.getElementById('gemini_key_sess_in').value;
        const newsapiKeySess = document.getElementById('newsapi_key_sess_in').value;
        
        const payload = {};
        if (geminiKeySess) payload.gemini_key = geminiKeySess;
        if (newsapiKeySess) payload.newsapi_key = newsapiKeySess;
        
        const currentTimestamp = new Date().toLocaleTimeString([], { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit', fractionalSecondDigits: 3 });

        if (Object.keys(payload).length === 0) {
            appendToLog({ timestamp: currentTimestamp, message: "No API keys entered to update in session.", level: "WARNING" });
            return;
        }
        
        loadingIndicator.style.display = 'block';
        try {
            const response = await fetch('/api/update-api-keys', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            const data = await response.json();
            appendToLog({ timestamp: currentTimestamp, message: data.message || "API Key session update response.", level: "INFO" });
            if (!response.ok) displayErrorMessages([data.message || `Error updating keys: ${response.status}`]);
            else displayErrorMessages([]); 
        } catch (error) {
            console.error('Error updating API keys:', error);
            appendToLog({ timestamp: currentTimestamp, message: `Client-side error updating API keys: ${error}`, level: "ERROR" });
            displayErrorMessages([`Client-side error updating keys: ${error}`]);
        } finally {
            loadingIndicator.style.display = 'none';
        }
    });

    // --- Sector Analysis Form Submission ---
    analysisForm.addEventListener('submit', async function (event) {
        event.preventDefault();
        runAnalysisBtn.disabled = true;
        loadingIndicator.style.display = 'block';
        resultsSummaryDiv.innerHTML = '<p>Processing sector analysis...</p>';
        
        Object.values(activeCharts).forEach(chart => {
            if (chart && typeof chart.destroy === 'function') chart.destroy();
        });
        activeCharts = {};
        sectorChartsContainer.innerHTML = ''; 
        sectorDetailsContainer.innerHTML = ''; 
        displayErrorMessages([]); 

        const formData = new FormData(analysisForm);
        const data = {}; 
        formData.forEach((value, key) => {
            if (key === 'selected_sectors') {
                if (!data[key]) data[key] = [];
                data[key].push(value);
            } else {
                data[key] = value;
            }
        });
        
        const currentTimestamp = new Date().toLocaleTimeString([], { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit', fractionalSecondDigits: 3 });
        appendToLog({ timestamp: currentTimestamp, message: `Starting SECTOR analysis... (News Source: ${data.sector_news_source || 'NewsAPI.org'})`, level: "INFO" });

        try {
            // Call the endpoint for SECTOR analysis ONLY
            const response = await fetch('/api/sector-analysis', { // Endpoint for sector-only analysis
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data)
            });
            const result = await response.json();

            if (result.logs && Array.isArray(result.logs)) {
                result.logs.forEach(logEntry => appendToLog(logEntry));
            }

            if (!response.ok || result.error) {
                // ... (error handling as before) ...
                const errorMessagesToDisplay = result.messages || (result.error && typeof result.error === 'string' ? [result.error] : [`Server error: ${response.status}. Check server logs.`]);
                displayErrorMessages(errorMessagesToDisplay);
                resultsSummaryDiv.innerHTML = `<p class="error-message">Sector analysis failed. Check errors and logs.</p>`;
            } else {
                const numResults = result.results ? result.results.length : 0;
                resultsSummaryDiv.innerHTML = `<p>Sector analysis complete. Found ${numResults} sector result(s).</p>`;
                displaySectorResultsAndStockOptions(result.results || []); // New display function
            }
        } catch (error) {
            // ... (client-side error handling as before) ...
            console.error('Client-side error during sector analysis:', error);
            appendToLog({ timestamp: new Date().toLocaleTimeString([], { hour12: false }), message: `Client-side error: ${error.message || error}`, level: "ERROR" });
            displayErrorMessages([`Client-side error: ${error.message || 'Network error.'}`]);
            resultsSummaryDiv.innerHTML = `<p class="error-message">A client-side error occurred during sector analysis.</p>`;
        } finally {
            runAnalysisBtn.disabled = false;
            loadingIndicator.style.display = 'none';
        }
    });

    // --- Chart Creation Helper (Keep as is) ---
    function createSentimentChart(canvasId, llmScore, vaderScore) {
        // ... (same as previous complete JS version)
        const chartLabels = [];
        const chartDataPoints = [];
        const chartBackgroundColors = [];
        const chartBorderColors = [];

        if (typeof llmScore === 'number' && !isNaN(llmScore)) {
            chartLabels.push('LLM');
            chartDataPoints.push(llmScore);
            chartBackgroundColors.push(llmScore > 0.1 ? 'rgba(75, 192, 192, 0.6)' : llmScore < -0.1 ? 'rgba(255, 99, 132, 0.6)' : 'rgba(201, 203, 207, 0.6)');
            chartBorderColors.push(llmScore > 0.1 ? 'rgba(75, 192, 192, 1)' : llmScore < -0.1 ? 'rgba(255, 99, 132, 1)' : 'rgba(201, 203, 207, 1)');
        }
        if (typeof vaderScore === 'number' && !isNaN(vaderScore)) {
            chartLabels.push('VADER Avg.');
            chartDataPoints.push(vaderScore);
            chartBackgroundColors.push(vaderScore > 0.05 ? 'rgba(54, 162, 235, 0.6)' : vaderScore < -0.05 ? 'rgba(255, 159, 64, 0.6)' : 'rgba(153, 102, 255, 0.6)'); 
            chartBorderColors.push(vaderScore > 0.05 ? 'rgba(54, 162, 235, 1)' : vaderScore < -0.05 ? 'rgba(255, 159, 64, 1)' : 'rgba(153, 102, 255, 1)');
        }

        if (chartDataPoints.length > 0) {
            const canvasElement = document.getElementById(canvasId);
            if (!canvasElement) {
                console.error(`Canvas element with ID ${canvasId} not found.`);
                return null;
            }
            const ctx = canvasElement.getContext('2d');
            return new Chart(ctx, { 
                type: 'bar',
                data: { /* ... data ... */ 
                    labels: chartLabels, 
                    datasets: [{
                        label: 'Sentiment Score',
                        data: chartDataPoints,
                        backgroundColor: chartBackgroundColors,
                        borderColor: chartBorderColors,
                        borderWidth: 1
                    }]
                },
                options: { /* ... options ... */
                    responsive: true, maintainAspectRatio: false,
                    scales: { y: { beginAtZero: false, min: -1, max: 1, title: { display: true, text: 'Score (-1 to 1)' } } },
                    plugins: { legend: { display: chartLabels.length > 1 }, title: { display: false } },
                    animation: { duration: 800, easing: 'easeInOutQuart' }
                }
            });
        }
        return null;
    }

    // --- Analysis Detail HTML Generation Helper (Keep as is) ---
    function generateAnalysisDetailHtml(analysisData, targetName, targetType = "sector") {
        // ... (same as previous complete JS version) ...
        let detailHtml = '';
        const geminiAnalysis = (targetType === "sector") ? analysisData.gemini_analysis_sector : analysisData.gemini_analysis_stock;
        const avgVaderScore = (targetType === "sector") ? analysisData.avg_vader_score_sector : analysisData.avg_vader_score_stock;
        const vaderSentimentLabel = (targetType === "sector") ? analysisData.vader_sentiment_label_sector : analysisData.vader_sentiment_label_stock;
        const numArticles = (targetType === "sector") ? analysisData.num_articles_for_llm_sector : analysisData.num_articles_for_llm_stock;
        const errorMessage = (targetType === "sector") ? analysisData.error_message_sector : analysisData.error_message_stock;

        if (targetType === "stock") { 
            detailHtml += `<p><small>Articles for LLM: ${numArticles !== undefined ? numArticles : 'N/A'}</small></p>`;
        }

        if (errorMessage) {
            detailHtml += `<p class="error-message"><strong>Error for this ${targetType}:</strong> ${escapeHtml(errorMessage)}</p>`;
        }
        
        if (typeof avgVaderScore === 'number' && !isNaN(avgVaderScore)) {
            detailHtml += `<p><strong>VADER Avg. Sentiment:</strong> ${escapeHtml(vaderSentimentLabel || 'N/A')} (Score: ${parseFloat(avgVaderScore).toFixed(3)})</p>`;
        } else {
            detailHtml += `<p><strong>VADER Avg. Sentiment:</strong> N/A</p>`;
        }

        if (geminiAnalysis) {
            const llmScore = geminiAnalysis.sentiment_score_llm;
            detailHtml += `<p><strong>LLM Overall Sentiment:</strong> ${escapeHtml(geminiAnalysis.overall_sentiment || 'N/A')} (Score: ${llmScore !== null && typeof llmScore !== 'undefined' && !isNaN(llmScore) ? parseFloat(llmScore).toFixed(2) : 'N/A'})</p>`;
            detailHtml += `<p><strong>LLM Summary:</strong> ${escapeHtml(geminiAnalysis.summary || 'N/A')}</p>`;
            detailHtml += `<p><strong>LLM Reason:</strong> ${escapeHtml(geminiAnalysis.sentiment_reason || 'N/A')}</p>`;
            
            const createListHtml = (items, listTitle) => {
                if (items && Array.isArray(items) && items.length > 0 && items.some(item => String(item || '').trim() !== '')) {
                    return `<strong>${listTitle}:</strong><ul>${items.map(item => `<li>${escapeHtml(item)}</li>`).join('')}</ul>`;
                } return `<strong>${listTitle}:</strong> N/A`;
            };
            detailHtml += createListHtml(geminiAnalysis.key_themes, 'LLM Key Themes');
            detailHtml += `<p><strong>LLM Potential Impact:</strong> ${escapeHtml(geminiAnalysis.potential_impact || 'N/A')}</p>`;
            detailHtml += createListHtml(geminiAnalysis.key_companies_mentioned_context, 'LLM Companies/Context');
            detailHtml += createListHtml(geminiAnalysis.risks_identified, 'LLM Risks');
            detailHtml += createListHtml(geminiAnalysis.opportunities_identified, 'LLM Opportunities');
        } else if (!errorMessage) { 
            detailHtml += `<p>No LLM analysis data available for this ${targetType}.</p>`;
        }
        return detailHtml;
    }

    // --- NEW: Display Sector Results AND Stock Analysis Options ---
    function displaySectorResultsAndStockOptions(allSectorResults) {
        sectorChartsContainer.innerHTML = ''; 
        sectorDetailsContainer.innerHTML = '';
        // No need to clear activeCharts here, as sector charts are persistent until next full run

        if (!allSectorResults || allSectorResults.length === 0) {
            sectorDetailsContainer.innerHTML = "<p>No sector results to display.</p>";
            return;
        }

        allSectorResults.forEach((sectorData, sectorIndex) => {
            // --- Display Sector Chart and Details (as before) ---
            const sectorChartWrapper = document.createElement('div');
            sectorChartWrapper.classList.add('chart-wrapper');
            const sectorCanvasId = `sectorChart-${sectorIndex}`; // Unique ID for sector chart
            const sectorCanvas = document.createElement('canvas');
            sectorCanvas.id = sectorCanvasId;
            
            let sectorLlmScoreVal = sectorData.gemini_analysis_sector ? sectorData.gemini_analysis_sector.sentiment_score_llm : null;
            let sectorVaderScoreVal = sectorData.avg_vader_score_sector;
            let sectorLlmScoreDisplay = (typeof sectorLlmScoreVal === 'number' && !isNaN(sectorLlmScoreVal)) ? parseFloat(sectorLlmScoreVal).toFixed(2) : 'N/A';
            let sectorVaderScoreDisplay = (typeof sectorVaderScoreVal === 'number' && !isNaN(sectorVaderScoreVal)) ? parseFloat(sectorVaderScoreVal).toFixed(2) : 'N/A';
            
            const sectorChartTitleElement = document.createElement('h4');
            sectorChartTitleElement.innerHTML = `SECTOR: ${escapeHtml(sectorData.sector_name)} <small>(LLM: ${sectorLlmScoreDisplay}, VADER Avg: ${sectorVaderScoreDisplay})</small>`;
            sectorChartWrapper.appendChild(sectorChartTitleElement);
            sectorChartWrapper.appendChild(sectorCanvas);
            sectorChartsContainer.appendChild(sectorChartWrapper);
            
            const sectorChartInstance = createSentimentChart(sectorCanvasId, sectorLlmScoreVal, sectorVaderScoreVal);
            if(sectorChartInstance) activeCharts[sectorCanvasId] = sectorChartInstance;
             else {
                const p = document.createElement('p');
                p.textContent = "Sector scores not available for chart.";
                p.classList.add('error-message');
                sectorCanvas.replaceWith(p);
            }

            const sectorDetailItem = document.createElement('div');
            sectorDetailItem.classList.add('result-item', 'sector-result-item'); 
            let sectorDetailHtml = `<h3>SECTOR: ${escapeHtml(sectorData.sector_name)}</h3>`;
            sectorDetailHtml += `<p><small>LLM Context Period: ${escapeHtml(sectorData.llm_context_date_range || 'N/A')} | Articles for Sector LLM: ${sectorData.num_articles_for_llm_sector !== undefined ? sectorData.num_articles_for_llm_sector : 'N/A'}</small></p>`;
            sectorDetailHtml += generateAnalysisDetailHtml(sectorData, sectorData.sector_name, "sector");
            
            // --- Add UI for Stock Analysis for this sector ---
            const stockAnalysisContainer = document.createElement('div');
            stockAnalysisContainer.classList.add('stock-analysis-trigger-container');
            stockAnalysisContainer.id = `stock-analysis-container-${sectorIndex}`;

            if (sectorData.constituent_stocks && sectorData.constituent_stocks.length > 0) {
                const stockSelectLabel = document.createElement('label');
                stockSelectLabel.htmlFor = `stock-select-${sectorIndex}`;
                stockSelectLabel.textContent = `Analyze Constituent Stocks for ${escapeHtml(sectorData.sector_name)}:`;
                
                const stockSelect = document.createElement('select');
                stockSelect.multiple = true;
                stockSelect.id = `stock-select-${sectorIndex}`;
                stockSelect.size = Math.min(sectorData.constituent_stocks.length, 5); // Show up to 5 stocks, or fewer if less

                sectorData.constituent_stocks.forEach(stockName => {
                    const option = document.createElement('option');
                    option.value = stockName;
                    option.textContent = escapeHtml(stockName);
                    stockSelect.appendChild(option);
                });

                const runStockAnalysisBtn = document.createElement('button');
                runStockAnalysisBtn.textContent = `Run Analysis for Selected Stocks`;
                runStockAnalysisBtn.classList.add('run-stock-analysis-btn');
                runStockAnalysisBtn.dataset.sectorName = sectorData.sector_name; // Store sector name
                runStockAnalysisBtn.dataset.sectorIndex = sectorIndex; // To find the right select

                stockAnalysisContainer.appendChild(stockSelectLabel);
                stockAnalysisContainer.appendChild(stockSelect);
                stockAnalysisContainer.appendChild(runStockAnalysisBtn);

                // Placeholder for where stock results will go for this sector
                const stockResultsDiv = document.createElement('div');
                stockResultsDiv.id = `stock-results-display-${sectorIndex}`;
                stockResultsDiv.classList.add('stock-results-area');
                stockAnalysisContainer.appendChild(stockResultsDiv);

            } else {
                stockAnalysisContainer.innerHTML = `<p><em>No constituent stocks configured for ${escapeHtml(sectorData.sector_name)}.</em></p>`;
            }
            sectorDetailItem.appendChild(stockAnalysisContainer); // Add stock UI to sector's detail item
            sectorDetailsContainer.appendChild(sectorDetailItem);
        });

        // Add event listeners to the newly created "Run Stock Analysis" buttons
        document.querySelectorAll('.run-stock-analysis-btn').forEach(button => {
            button.addEventListener('click', handleRunStockAnalysis);
        });
    }

    async function handleRunStockAnalysis(event) {
        const button = event.target;
        const sectorName = button.dataset.sectorName;
        const sectorIndex = button.dataset.sectorIndex;
        const stockSelectElement = document.getElementById(`stock-select-${sectorIndex}`);
        
        const selectedStockOptions = Array.from(stockSelectElement.selectedOptions);
        const selectedStocks = selectedStockOptions.map(opt => opt.value);

        if (selectedStocks.length === 0) {
            appendToLog({ timestamp: new Date().toLocaleTimeString([], { hour12: false }), message: `No stocks selected for ${sectorName}.`, level: "WARNING" });
            alert(`Please select stocks to analyze for ${sectorName}.`);
            return;
        }

        button.disabled = true;
        loadingIndicator.style.display = 'block'; // Show global loading indicator or a local one

        // Get parameters from the main form for consistency (dates, lookback, custom prompt)
        // Max articles for stock can be from a dedicated input or hardcoded in app.py
        const endDate = document.getElementById('end_date').value;
        const lookbackDays = document.getElementById('sector_lookback').value;
        const stockMaxArticles = document.getElementById('stock_max_articles') ? document.getElementById('stock_max_articles').value : 3; // Fallback if input not present
        const customPrompt = document.getElementById('sector_custom_prompt').value;

        const payload = {
            sector_name: sectorName,
            selected_stocks: selectedStocks,
            end_date: endDate,
            lookback_days: lookbackDays,
            stock_max_articles: parseInt(stockMaxArticles, 10),
            custom_prompt: customPrompt
        };

        appendToLog({ timestamp: new Date().toLocaleTimeString([], { hour12: false }), message: `Starting analysis for selected stocks in ${sectorName}...`, level: "INFO" });

        try {
            const response = await fetch('/api/stock-analysis', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            const result = await response.json();

            if (result.logs && Array.isArray(result.logs)) {
                result.logs.forEach(logEntry => appendToLog(logEntry));
            }

            const stockResultsDisplayArea = document.getElementById(`stock-results-display-${sectorIndex}`);
            stockResultsDisplayArea.innerHTML = ''; // Clear previous stock results for this sector

            if (!response.ok || result.error) {
                const errorMessages = result.messages || [`Stock analysis server error: ${response.status}`];
                displayErrorMessages(errorMessages); // Display globally or locally
                stockResultsDisplayArea.innerHTML = `<p class="error-message">Stock analysis failed. Check errors.</p>`;
            } else {
                displayIndividualStockResults(result.results_stocks || [], stockResultsDisplayArea);
            }

        } catch (error) {
            console.error(`Error during stock analysis for ${sectorName}:`, error);
            appendToLog({ timestamp: new Date().toLocaleTimeString([], { hour12: false }), message: `Client-side error during stock analysis for ${sectorName}: ${error}`, level: "ERROR" });
            const stockResultsDisplayArea = document.getElementById(`stock-results-display-${sectorIndex}`);
            if (stockResultsDisplayArea) {
                 stockResultsDisplayArea.innerHTML = `<p class="error-message">A client-side error occurred during stock analysis.</p>`;
            }
        } finally {
            button.disabled = false;
            loadingIndicator.style.display = 'none';
        }
    }

    function displayIndividualStockResults(stockResults, containerElement) {
        if (!stockResults || stockResults.length === 0) {
            containerElement.innerHTML = "<p><em>No analysis results for selected stocks.</em></p>";
            return;
        }
        
        const stockListContainerHtml = stockResults.map(stockData => {
            let stockDetailHtml = `<div class="result-item stock-result-item">`;
            
            let stockLlmScore = stockData.gemini_analysis_stock ? stockData.gemini_analysis_stock.sentiment_score_llm : null;
            let stockVaderScore = stockData.avg_vader_score_stock;
            let stockLlmScoreDisp = (typeof stockLlmScore === 'number' && !isNaN(stockLlmScore)) ? parseFloat(stockLlmScore).toFixed(2) : 'N/A';
            let stockVaderScoreDisp = (typeof stockVaderScore === 'number' && !isNaN(stockVaderScore)) ? parseFloat(stockVaderScore).toFixed(2) : 'N/A';

            stockDetailHtml += `<h5>${escapeHtml(stockData.stock_name)} <small>(LLM: ${stockLlmScoreDisp}, VADER Avg: ${stockVaderScoreDisp})</small></h5>`;
            stockDetailHtml += generateAnalysisDetailHtml(stockData, stockData.stock_name, "stock");
            stockDetailHtml += `</div>`;
            return stockDetailHtml;
        }).join('');
        
        containerElement.innerHTML = `<div class="stock-list-container">${stockListContainerHtml}</div>`;
    }


    // Initial log message
    appendToLog({ timestamp: new Date().toLocaleTimeString([], { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit', fractionalSecondDigits: 3 }), message: "Frontend initialized. Ready.", level: "INFO" });
});