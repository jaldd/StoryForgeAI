package ai.storyforge.infrastructure.config;

import dev.langchain4j.model.chat.ChatLanguageModel;
import dev.langchain4j.model.chat.StreamingChatLanguageModel;
import dev.langchain4j.model.openai.OpenAiChatModel;
import dev.langchain4j.model.openai.OpenAiStreamingChatModel;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class LlmConfig {

    private static final String DEMO_BASE_URL = "http://langchain4j.dev/demo/openai/v1";
    private static final String DEMO_API_KEY = "demo";
    private static final String DEMO_MODEL = "gpt-4o-mini";

    @Bean
    ChatLanguageModel chatLanguageModel(ModelProperties properties) {
        ModelProperties.Provider provider = properties.providers().get(0);
        String apiKey = provider.apikey();

        OpenAiChatModel.OpenAiChatModelBuilder builder = OpenAiChatModel.builder()
                .maxTokens(provider.maxTokens())
                .temperature(provider.temperature());

        if (DEMO_API_KEY.equals(apiKey)) {
            builder.baseUrl(DEMO_BASE_URL)
                    .apiKey(DEMO_API_KEY)
                    .modelName(DEMO_MODEL);
        } else {
            builder.baseUrl(provider.endpoint())
                    .apiKey(apiKey)
                    .modelName(provider.model());
        }

        return builder.build();
    }

    @Bean
    StreamingChatLanguageModel streamingChatLanguageModel(ModelProperties properties) {
        ModelProperties.Provider provider = properties.providers().get(0);
        String apiKey = provider.apikey();

        OpenAiStreamingChatModel.OpenAiStreamingChatModelBuilder builder = OpenAiStreamingChatModel.builder()
                .maxTokens(provider.maxTokens())
                .temperature(provider.temperature());

        if (DEMO_API_KEY.equals(apiKey)) {
            builder.baseUrl(DEMO_BASE_URL)
                    .apiKey(DEMO_API_KEY)
                    .modelName(DEMO_MODEL);
        } else {
            builder.baseUrl(provider.endpoint())
                    .apiKey(apiKey)
                    .modelName(provider.model());
        }

        return builder.build();
    }
}
