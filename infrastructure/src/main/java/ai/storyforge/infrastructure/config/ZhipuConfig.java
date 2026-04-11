package ai.storyforge.infrastructure.config;

import ai.z.openapi.ZhipuAiClient;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class ZhipuConfig {

    @Bean
    public ZhipuAiClient zhipuAiClient(ModelProperties properties) {
        ModelProperties.Provider provider = properties.providers().get(0);
        String apiKey = provider.apikey();

        return ZhipuAiClient.builder()
                .ofZHIPU()
                .apiKey(apiKey)
                .build();
    }
}
