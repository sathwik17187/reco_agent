<h1>Razorpay — AI Revenue Recovery Agent</h1>
    <div>
        <img src="https://upload.wikimedia.org/wikipedia/commons/8/89/Razorpay_logo.svg" alt="Razorpay Logo" style="height:60px;width:200px;">
    </div>
    <hr>
    <div id="Toc">
        <h2>Table of Contents</h2>
            <a href="#abstract">- Introduction</a><br>
            <a href="#req">- Requirements</a><br>
            <a href="#ins">- How to Use</a><br>
            <a href="#preview">- Preview</a><br>
            <a href="#Team">- Team</a><br>
            <a href="#cont">- Contribution</a><br>
            <a href="#improve">- Improvements</a><br>
    </div>
    <hr>
    <div id="abstract">
        <h2>Abstract</h2>
        <p>This application provides an intelligent, autonomous Revenue Recovery Agent designed for modern digital commerce and subscription platforms. It proactively recovers lost revenue across failed recurring payments, abandoned checkouts, and overdue invoices while strictly upholding brand trust and compliance policies.<br>
        The system employs a multi-tiered decision engine: deterministic rule-based detection for immediate risk classification, a ChromaDB vector database with nomic-embed-text embeddings for policy knowledge retrieval (RAG), and a local Ollama LLM (Qwen 2.5 / Llama 3) for diagnosing ambiguous churn risks and merchant-specific policies.<br>
        Interventions are sequenced and executed through a state machine built with LangGraph, respecting cooling-off intervals, Do-Not-Contact (DNC) registries, and escalation hierarchies. It produces localized Hinglish SMS, email, and simulated IVR communications tailored to customer segments.<br>
        The platform features an executive Command Center dashboard built with React, Vite, and TailwindCSS, backed by a FastAPI server, enabling real-time telemetry, audit trail examination, ground-truth accuracy benchmarking, and an interactive event simulator.</p>
    </div>
    <hr>
    <div id="req">
        <h2>Requirements</h2>
        <table style="border-collapse: collapse;">
            <tr>
                <th>Python</th>
                <td>
                    <a href="https://www.python.org/downloads/">v3.10+</a>
                </td>
            </tr>
            <tr>
                <th>Ollama</th>
                <td>
                    <a href="https://ollama.com/">v0.3.0+</a>
                </td>
            </tr>
            <tr>
                <th>LangGraph</th>
                <td>
                    <a href="https://www.langchain.com/langgraph">v0.2.0+</a>
                </td>
            </tr>
            <tr>
                <th>ChromaDB</th>
                <td>
                    <a href="https://www.trychroma.com/">v0.5.0+</a>
                </td>
            </tr>
            <tr>
                <th>FastAPI + Uvicorn</th>
                <td>
                    <a href="https://fastapi.tiangolo.com/">v0.110.0+</a>
                </td>
            </tr>
            <tr>
                <th>Vite + React</th>
                <td>
                    <a href="https://vite.dev/guide/">v7.1.9</a>
                </td>
            </tr>
            <tr>
                <th>TailwindCSS</th>
                <td>
                    <a href="https://tailwindcss.com/">v3.4.0+</a>
                </td>
            </tr>
        </table>
    </div>
    <hr>
    <div id="ins">
        <h2>How to Use</h2>
        <ol>
            <li>Clone the repository using <br>
            <pre><code>git clone https://github.com/sathwik17187/reco_agent.git</code></pre></li>
            <li>Navigate to the project directory:<br><pre><code>cd reco_agent</code></pre></li>
            <li>Install Python dependencies:
                <pre><code>pip install -r recovery_agent/requirements.txt fastapi uvicorn pandas</code></pre>
            </li>
            <li>Pull the required Ollama models:
                <pre><code>ollama pull nomic-embed-text<br>ollama pull qwen2.5:0.5b</code></pre>
            </li>
            <li>Run the end-to-end recovery pipeline:
                <pre><code>python run_agent.py</code></pre>
            </li>
            <li>Start the Command Center web server and dashboard:
                <pre><code>python api_server.py</code></pre>
            </li>
            <li>Open your browser and navigate to the provided localhost URL to view the application:
                <pre><code>http://localhost:8000</code></pre>
            </li>
        </ol>
    </div>
    <hr>
    <div id="preview">
            <h2>Preview</h2>
            <img src="docs/images/dashboard_overview.png" alt="Executive Dashboard Overview"><br>
            <img src="docs/images/case_auditor.png" alt="Case Explorer and RAG Trace"><br>
            <img src="docs/images/live_simulator.png" alt="Live Event Simulator">
    </div>
    <hr>
    <div id="Team">
        <h2>Team Details</h2>
        <p>Team Number: <br>25AACR17</p>
        <p>Senior Mentor: <br>Vaishnavi Addla</p>
        <p>Junior Mentor: <br>Dheeraj Chandra</p>
        <p>Team Member 1: <br>Sai Sathwik</p>
        <p>Team Member 2: <br>Chandu Chethan</p>
        <p>Team Member 3: <br>Divya</p>
        <p>Team Member 4: <br>Anvitha</p>
    </div>
    <hr>
    <div id="cont">
        <h2>Contribution</h2>
          <strong>This section provides instructions and details on how to submit a contribution via a pull request. It is important to follow these guidelines to make sure your pull request is accepted.</strong> 
        <br>
            1. Before choosing to propose changes to this project, it is advisable to go through the readme.md file of the project to get the philosophy and the motive that went behind this project. The pull request should align with the philosophy and the motive of the original poster of this project. <br>
            2. To add your changes, make sure that the programming language in which you are proposing the changes should be the same as the programming language that has been used in the project. The versions of the programming language and the libraries(if any) used should also match with the original code. <br>
            3. Write a documentation on the changes that you are proposing. The documentation should include the problems you have noticed in the code(if any), the changes you would like to propose, the reason for these changes, and sample test cases. Remember that the topics in the documentation are strictly not limited to the topics aforementioned, but are just an inclusion. <br>
            4. Submit a pull request via <a href="https://gist.github.com/mikepea/863f63d6e37281e329f8">Git etiquette</a>
        <br>
    </div>
    <hr>
    <div id="improve">
        <h2>Improvements</h2>
        <ul>
            <li>Integrate dynamic WhatsApp Business API and conversational bots for interactive repayment links and EMI inquiries.</li>
            <li>Incorporate real-time ML credit score lookups to dynamically adjust discount authorization bands based on merchant margin thresholds.</li>
            <li>Add multi-gateway smart retry routing to dynamically swap payment aggregators during bank network outages.</li>
            <li>Enhance Hinglish voice synthesis with real-time bidirectional telephony connectors (e.g., Twilio / Exotel).</li>
            <li>Implement automated merchant escalation webhooks into Slack, Zendesk, and Salesforce for high-value VIP accounts.</li>
        </ul>
    </div>
