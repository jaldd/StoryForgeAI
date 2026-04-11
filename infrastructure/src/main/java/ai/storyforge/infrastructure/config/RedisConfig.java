package ai.storyforge.infrastructure.config;

import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Configuration;
import org.springframework.data.redis.repository.configuration.EnableRedisRepositories;

@Configuration
@ConditionalOnProperty(name = "app.redis.enabled", havingValue = "true")
@EnableRedisRepositories(basePackages = "ai.storyforge.infrastructure.persistence.redis")
public class RedisConfig {
}
