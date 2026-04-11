package ai.storyforge.infrastructure.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

import java.util.List;

@ConfigurationProperties(prefix = "model")
public record ModelProperties(List<Provider> providers) {
    public record Provider(
            String name,
            String endpoint,
            String model,
            String apikey,
            int maxTokens,
            double temperature,
            double topP
    ) {}
}
