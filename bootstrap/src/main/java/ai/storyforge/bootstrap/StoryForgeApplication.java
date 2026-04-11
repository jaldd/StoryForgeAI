package ai.storyforge.bootstrap;

import ai.storyforge.infrastructure.config.ModelProperties;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.autoconfigure.domain.EntityScan;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.ComponentScan;
import org.springframework.data.jpa.repository.config.EnableJpaRepositories;

@SpringBootApplication
@ComponentScan(basePackages = "ai.storyforge")
@EntityScan(basePackages = "ai.storyforge.domain.model")
@EnableJpaRepositories(basePackages = "ai.storyforge.infrastructure.persistence")
@EnableConfigurationProperties(ModelProperties.class)
public class StoryForgeApplication {

    public static void main(String[] args) {
        SpringApplication.run(StoryForgeApplication.class, args);
    }
}
