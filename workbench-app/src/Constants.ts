// Allow static build of React code to access env vars
// SEE https://create-react-app.dev/docs/title-and-meta-tags/#injecting-data-from-the-server-into-the-page
const serviceUrl =
    window.VITE_SEMANTIC_WORKBENCH_SERVICE_URL && window.VITE_SEMANTIC_WORKBENCH_SERVICE_URL.startsWith('https://')
        ? window.VITE_SEMANTIC_WORKBENCH_SERVICE_URL
        : import.meta.env.VITE_SEMANTIC_WORKBENCH_SERVICE_URL
        ? import.meta.env.VITE_SEMANTIC_WORKBENCH_SERVICE_URL
        : 'http://127.0.0.1:3000';

export const Constants = {
    app: {
        name: 'Semantic Workbench',
        defaultTheme: 'light',
        defaultBrand: 'local',
        autoScrollThreshold: 100,
        maxContentWidth: 900,
        maxInputLength: 2000000, // 2M tokens, effectively unlimited
        conversationListMinWidth: '250px',
        conversationHistoryMinWidth: '270px',
        resizableCanvasDrawerMinWidth: '200px',
        get resizableCanvasDrawerMaxWidth() {
            return `calc(100vw - ${this.conversationListMinWidth} - ${this.conversationHistoryMinWidth})`;
        },
        defaultChatWidthPercent: 33,
        maxFileAttachmentsPerMessage: 10,
        loaderDelayMs: 100,
        responsiveBreakpoints: {
            chatCanvas: '900px',
        },
        speechIdleTimeoutMs: 4000,
        azureSpeechTokenRefreshIntervalMs: 540000, // 540000 ms = 9 minutes
        globalToasterId: 'global',
    },
    service: {
        defaultEnvironmentId: 'local',
        environments: [
            {
                id: 'local',
                name: 'Semantic Workbench backend service on localhost or GitHub Codespaces',
                // Can be overridden by env var VITE_SEMANTIC_WORKBENCH_SERVICE_URL
                url: serviceUrl,
                brand: 'light',
            },
            // {
            //     id: 'remote',
            //     name: 'Remote',
            //     url: 'https://<YOUR WORKBENCH DEPLOYMENT>.azurewebsites.net',
            //     brand: 'orange',
            // },
        ],
    },
    assistantCategories: {
        Recommended: ['explorer-assistant.made-exploration-team', 'guided-conversation-assistant.made-exploration'],
        'Example Implementations': [
            'python-01-echo-bot.workbench-explorer',
            'python-02-simple-chatbot.workbench-explorer',
            'python-03-multimodel-chatbot.workbench-explorer',
            'canonical-assistant.semantic-workbench',
        ],
        Experimental: ['prospector-assistant.made-exploration'],
    },
    msal: {
        method: 'redirect', // 'redirect' | 'popup'
        auth: {
            // Semantic Workbench GitHub sample app registration
            // The same value is set also in AuthSettings in
            // "semantic_workbench_service.config.py" in the backend
            // Can be overridden by env var VITE_SEMANTIC_WORKBENCH_CLIENT_ID
            clientId: import.meta.env.VITE_SEMANTIC_WORKBENCH_CLIENT_ID || '22cb77c3-ca98-4a26-b4db-ac4dcecba690',

            // Specific tenant only:     'https://login.microsoftonline.com/<tenant>/',
            // Personal accounts only:   'https://login.microsoftonline.com/consumers',
            // Work + School accounts:   'https://login.microsoftonline.com/organizations',
            // Work + School + Personal: 'https://login.microsoftonline.com/common'
            // Can be overridden by env var VITE_SEMANTIC_WORKBENCH_AUTHORITY
            authority: import.meta.env.VITE_SEMANTIC_WORKBENCH_AUTHORITY || 'https://login.microsoftonline.com/common',
        },
        cache: {
            cacheLocation: 'localStorage',
            storeAuthStateInCookie: false,
        },
        // Enable the ones you need
        msGraphScopes: [
            // 'Calendars.ReadWrite',
            // 'Calendars.Read.Shared',
            // 'ChannelMessage.Read.All',
            // 'Chat.Read',
            // 'Contacts.Read',
            // 'Contacts.Read.Shared',
            // 'email',
            // 'Files.Read',
            // 'Files.Read.All',
            // 'Files.Read.Selected',
            // 'Group.Read.All',
            // 'Mail.Read',
            // 'Mail.Read.Shared',
            // 'MailboxSettings.Read',
            // 'Notes.Read',
            // 'Notes.Read.All',
            // 'offline_access',
            // 'OnlineMeetingArtifact.Read.All',
            // 'OnlineMeetings.Read',
            'openid',
            // 'People.Read',
            // 'Presence.Read.All',
            'offline_access',
            'profile',
            // 'Sites.Read.All',
            // 'Tasks.Read',
            // 'Tasks.Read.Shared',
            // 'TeamSettings.Read.All',
            'User.Read',
            // 'User.Read.all',
            // 'User.ReadBasic.All',
        ],
    },
    debug: {
        root: 'semantic-workbench',
    },
};
